"""Daily, bounded rechecks of owner-bound subscriptions; never formal posting.

Each daily cycle rereads from the owner's original cutoff, including old unpaid
invoices that may have been paid much later without a delivered notification.
Only a complete cycle advances coverage. Page cursors and leased claims survive
restarts; a page and its evidence commit together under the existing workflow lock.
"""
import asyncio
import contextlib
import os
import secrets
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from models.stripe_history_daily_scan import StripeHistoryScanState
from models.stripe_history_reconciliation import StripeHistoryBinding, StripeHistoryInvoiceReview, StripeHistoryPosting
from services import stripe_history_provider as provider
from services.sales_deal_payments import _id, _instant
from services.sales_payment_catalog import STRIPE_ACCOUNT_ID
from services.sales_workflow_locks import lock_sales_workflow
from services.stripe_history_reconciliation import day, invoice_subscription, owner, save_invoice, utc

BEIJING = ZoneInfo("Asia/Shanghai")
LEASE_SECONDS = 90
PAGE_TIMEOUT_SECONDS = 25
MAX_BATCH_PAGES = 4
BATCH_SECONDS = 60
WINDOW_DAYS = 93
STARTUP_DELAY_SECONDS = 300
POLL_SECONDS = 60


def now():
    return datetime.now(timezone.utc)


def enabled():
    return (os.getenv("STRIPE_HISTORY_DAILY_SCAN_ENABLED") or "true").strip().lower() not in {"0", "false", "no", "off"}


def scheduled_target(at):
    local = utc(at).astimezone(BEIJING)
    target = datetime.combine(local.date(), time(9), tzinfo=BEIJING)
    if target > local:
        target -= timedelta(days=1)
    return target.astimezone(timezone.utc)


def next_scheduled(at):
    return scheduled_target(at) + timedelta(days=1)


def active_bindings():
    return (StripeHistoryBinding.account_id == STRIPE_ACCOUNT_ID,
        StripeHistoryBinding.livemode.is_(True), StripeHistoryBinding.status == "active")


def sessions_factory():
    from core.database import db_manager
    return db_manager.async_session_maker


async def claim_page(sessions, at):
    """One durable CAS lease per binding. Provider I/O happens after commit."""
    target = scheduled_target(at)
    target_day = target.astimezone(BEIJING).date().isoformat()
    async with sessions() as db:
        # Oldest-attempt first gives each binding a turn, even if another has
        # hundreds of pages or repeatedly fails. Null states are first.
        wanted = await db.scalar(select(StripeHistoryBinding.id).outerjoin(StripeHistoryScanState,
            StripeHistoryScanState.binding_id == StripeHistoryBinding.id).where(*active_bindings(),
            or_(StripeHistoryScanState.completed_for.is_(None), StripeHistoryScanState.completed_for < target_day),
            or_(StripeHistoryScanState.lease_until.is_(None), StripeHistoryScanState.lease_until <= at),
            or_(StripeHistoryScanState.retry_at.is_(None), StripeHistoryScanState.retry_at <= at))
            .order_by(func.coalesce(StripeHistoryScanState.last_attempt_at, datetime(1970, 1, 1)), StripeHistoryBinding.id).limit(1))
        if wanted is None:
            return None
        state = await db.get(StripeHistoryScanState, wanted)
        if state is None:
            try:
                async with db.begin_nested():
                    db.add(StripeHistoryScanState(binding_id=wanted, failure_count=0, page_count=0, invoice_count=0, discovered_count=0))
                    await db.flush()
            except IntegrityError:
                pass  # Another process inserted the same single checkpoint.
        token = secrets.token_hex(24)
        claimed = await db.execute(update(StripeHistoryScanState).where(StripeHistoryScanState.binding_id == wanted,
            or_(StripeHistoryScanState.lease_until.is_(None), StripeHistoryScanState.lease_until <= at),
            or_(StripeHistoryScanState.retry_at.is_(None), StripeHistoryScanState.retry_at <= at),
            or_(StripeHistoryScanState.completed_for.is_(None), StripeHistoryScanState.completed_for < target_day),
            exists(select(StripeHistoryBinding.id).where(StripeHistoryBinding.id == wanted, *active_bindings())))
            .values(lease_token=token, lease_until=at + timedelta(seconds=LEASE_SECONDS), last_attempt_at=at))
        if claimed.rowcount != 1:
            await db.rollback()
            return None
        binding = await db.get(StripeHistoryBinding, wanted, populate_existing=True)
        state = await db.get(StripeHistoryScanState, wanted, populate_existing=True)
        if state.scan_for is None or state.scan_for == state.completed_for:
            start = datetime.combine(day(binding.sync_from), time(), timezone.utc)
            state.scan_for, state.target_end = target_day, target
            state.range_start, state.range_end = start, min(start + timedelta(days=WINDOW_DAYS), target)
            state.cursor, state.retry_at, state.last_error_code = None, None, None
            state.page_count, state.invoice_count, state.discovered_count = 0, 0, 0
        job = {"binding_id": wanted, "token": token, "subscription_id": binding.stripe_subscription_id,
            "stripe_customer_id": binding.stripe_customer_id,
            "range_start": utc(state.range_start), "range_end": utc(state.range_end), "cursor": state.cursor}
        await db.commit()
        return job


async def fail_page(sessions, job, at, code):
    async with sessions() as db:
        state = await db.get(StripeHistoryScanState, job["binding_id"])
        if state is None or state.lease_token != job["token"]:
            return
        state.failure_count += 1
        state.retry_at = at + timedelta(seconds=min(3600, 60 * 2 ** min(state.failure_count - 1, 6)))
        state.last_error_code = code
        state.lease_token = state.lease_until = None
        await db.commit()


async def finish_page(sessions, job, rows, more, at):
    """A failed save rolls back the whole page AND its cursor, for safe replay."""
    if not isinstance(rows, list) or len(rows) > provider.PAGE_LIMIT or type(more) is not bool:
        raise ValueError("provider_page_invalid")
    identities = []
    for raw in rows:
        identity = _id(raw.get("id"), "in_") if isinstance(raw, dict) else None
        created = _instant(raw.get("created")) if isinstance(raw, dict) else None
        if (not identity or not created or not job["range_start"] <= created < job["range_end"]
                or raw.get("livemode") is not True or invoice_subscription(raw) != job["subscription_id"]
                or _id(raw.get("customer"), "cus_") != job["stripe_customer_id"]):
            raise ValueError("invoice_scope_invalid")
        identities.append(identity)
    if len(set(identities)) != len(identities) or (more and (not identities or identities[-1] == job["cursor"])):
        raise ValueError("provider_cursor_invalid")
    async with sessions() as db:
        await lock_sales_workflow(db)
        state = await db.get(StripeHistoryScanState, job["binding_id"], populate_existing=True)
        binding = await db.get(StripeHistoryBinding, job["binding_id"], populate_existing=True)
        if (not state or state.lease_token != job["token"] or not state.lease_until or utc(state.lease_until) <= at):
            return False  # Lease was lost: no evidence write, no cursor advance.
        if not binding or binding.status != "active" or binding.account_id != STRIPE_ACCOUNT_ID or binding.livemode is not True:
            state.lease_token = state.lease_until = None
            await db.commit()
            return False
        if binding.stripe_subscription_id != job["subscription_id"] or binding.stripe_customer_id != job["stripe_customer_id"]:
            raise ValueError("invoice_scope_invalid")
        old_ids = set((await db.scalars(select(StripeHistoryInvoiceReview.stripe_invoice_id).where(
            StripeHistoryInvoiceReview.account_id == STRIPE_ACCOUNT_ID, StripeHistoryInvoiceReview.livemode.is_(True),
            StripeHistoryInvoiceReview.stripe_invoice_id.in_(identities)))).all()) if identities else set()
        for raw in rows:
            await save_invoice(db, binding, raw)
        state.page_count += 1
        state.invoice_count += len(rows)
        state.discovered_count += len(set(identities) - old_ids)
        state.failure_count, state.retry_at, state.last_error_code = 0, None, None
        if more:
            state.cursor = identities[-1]
        elif utc(state.range_end) < utc(state.target_end):
            state.range_start = state.range_end
            state.range_end = min(utc(state.range_start) + timedelta(days=WINDOW_DAYS), utc(state.target_end))
            state.cursor = None
        else:
            state.completed_for = state.scan_for
            state.covered_through = state.target_end
            state.last_completed_at = at
            state.cursor = None
        state.lease_token = state.lease_until = None
        await db.commit()
        return True


async def run_batch(*, sessions=None, reader=None, clock=None, max_pages=MAX_BATCH_PAGES):
    sessions = sessions or sessions_factory()
    if sessions is None:
        return {"processed_pages": 0, "deferred": True}
    clock = clock or now
    reader = reader or provider.reader()
    processed = failed = 0
    try:
        async with asyncio.timeout(BATCH_SECONDS):
            for _ in range(min(max_pages, MAX_BATCH_PAGES)):
                job = await claim_page(sessions, clock())
                if job is None:
                    break
                try:
                    if job["range_start"] >= job["range_end"]:
                        rows, more = [], False
                    else:
                        rows, more = await asyncio.wait_for(reader.invoices(job["subscription_id"], int(job["range_start"].timestamp()),
                            int(job["range_end"].timestamp()), job["cursor"]), timeout=PAGE_TIMEOUT_SECONDS)
                    if await finish_page(sessions, job, rows, more, clock()):
                        processed += 1
                except asyncio.CancelledError:
                    raise  # Durable lease expires; the next process resumes the page.
                except Exception as error:
                    code = str(error) if isinstance(error, ValueError) and str(error) in {
                        "provider_page_invalid", "invoice_scope_invalid", "provider_cursor_invalid"} else (
                        "provider_unavailable" if isinstance(error, (HTTPException, TimeoutError)) else "scan_failed")
                    await fail_page(sessions, job, clock(), code)
                    failed += 1
    except TimeoutError:
        return {"processed_pages": processed, "failed_pages": failed, "deferred": True}
    return {"processed_pages": processed, "failed_pages": failed, "deferred": False}


async def scheduler_loop():
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            await run_batch()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # No provider payload, credential or customer content in logs.
        await asyncio.sleep(POLL_SECONDS)


def start_daily_scan():
    if not enabled() or os.getenv("IS_LAMBDA") == "true":
        return None
    return asyncio.create_task(scheduler_loop(), name="stripe-history-daily-scan")


async def stop_daily_scan(task):
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def reminders(db, user):
    await owner(db, user)
    at = now()
    selected = (await db.execute(select(StripeHistoryInvoiceReview, StripeHistoryBinding, StripeHistoryPosting)
        .join(StripeHistoryBinding, StripeHistoryBinding.id == StripeHistoryInvoiceReview.binding_id)
        .outerjoin(StripeHistoryPosting, StripeHistoryPosting.review_id == StripeHistoryInvoiceReview.id)
        .where(StripeHistoryBinding.account_id == STRIPE_ACCOUNT_ID, StripeHistoryBinding.livemode.is_(True),
            StripeHistoryInvoiceReview.account_id == STRIPE_ACCOUNT_ID, StripeHistoryInvoiceReview.livemode.is_(True))
        .order_by(StripeHistoryInvoiceReview.observed_at.desc(), StripeHistoryInvoiceReview.id.desc()))).all()
    items = []
    for review, binding, posting in selected:
        changed = bool(posting and (posting.fingerprint != review.fingerprint or review.snapshot.get("issues") or review.needs_refresh))
        kind = "exception" if changed else "needs_refresh" if review.needs_refresh else review.status
        if kind not in {"pending_review", "needs_refresh", "exception"}:
            continue
        items.append({"id": review.id, "kind": kind, "customer_name": binding.crm_snapshot["customer_name"],
            "package_name": binding.crm_snapshot["package_name"], "title": "已核账凭据发生变化，请核对原调整流程" if changed else {
                "pending_review": "续费收款待老板核对", "needs_refresh": "付款凭据待刷新", "exception": "付款依据存在异常，请核对"}[kind],
            "href": f"/finance?tab=stripe_reconciliation&stripe_view=reviews&stripe_review={review.id}", "observed_at": review.observed_at})
    counts = {kind: sum(item["kind"] == kind for item in items) for kind in ("pending_review", "needs_refresh", "exception")}
    counts["total"] = len(items)
    active = (await db.scalars(select(StripeHistoryBinding).where(*active_bindings()))).all()
    states = (await db.scalars(select(StripeHistoryScanState).where(StripeHistoryScanState.binding_id.in_([row.id for row in active])))).all() if active else []
    due = scheduled_target(at).astimezone(BEIJING).date().isoformat()
    covered = sum(bool(row.completed_for and row.completed_for >= due) for row in states)
    running = sum(bool(row.lease_until and utc(row.lease_until) > at) for row in states)
    retries = sum(bool(row.last_error_code) for row in states)
    attempted = [row for row in states if row.last_attempt_at]
    latest = max(attempted, key=lambda row: utc(row.last_attempt_at), default=None)
    latest_cycle = max([row.scan_for for row in states if row.scan_for], default=None)
    completed_dates = [utc(row.last_completed_at) for row in states if row.last_completed_at]
    complete_coverage = [utc(row.covered_through) for row in states if row.covered_through]
    is_enabled = enabled() and os.getenv("IS_LAMBDA") != "true"
    last_status = "disabled" if not is_enabled else "no_bindings" if not active else "running" if running else "retrying" if retries else "completed" if covered == len(active) else "partial" if attempted else "never"
    exceptions = [item for item in items if item["kind"] == "exception"]
    return {"counts": counts, "items": items[:20], "exception_items": exceptions[:20],
        "exception_has_more": len(exceptions) > 20, "auto_accounting": False, "daily_scan": {
        "enabled": is_enabled, "timezone": "Asia/Shanghai", "daily_time": "09:00",
        "next_scheduled_at": next_scheduled(at), "last_completed_at": max(completed_dates, default=None),
        "last_run_at": utc(latest.last_attempt_at) if latest else None, "last_run_status": last_status,
        "last_discovered_reviews": sum(row.discovered_count for row in states if row.scan_for == latest_cycle) if latest_cycle else None,
        "active_bindings": len(active), "covered_bindings": covered, "catchup_bindings": len(active) - covered,
        "retry_bindings": retries, "running_bindings": running,
        "last_error_code": next((row.last_error_code for row in sorted(attempted, key=lambda row: utc(row.last_attempt_at), reverse=True) if row.last_error_code), None),
        "window_start": utc(latest.range_start) if latest and latest.range_start else None,
        "window_end": utc(latest.range_end) if latest and latest.range_end else None,
        "covered_through": min(complete_coverage) if len(complete_coverage) == len(active) and active else None,
        "note": "补查仅使用专用只读连接生成待核对记录；实际税费与手续费仍需逐笔核对，不自动记账。"}}
