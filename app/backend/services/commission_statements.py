"""Monthly channel settlement. These functions never initiate a money transfer."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, func, inspect, or_, select, text

from models.commissions import (
    CommissionAgreement, CommissionEntry, CommissionStatement, CommissionStatementLine,
    CommissionStatusEvent, CustomerCommissionAttribution, SalesPartner,
)
from models.customers import Customers
from models.finance_profit_closes import MonthlyProfitClose
from models.payments import Payments
from services.commissions import (
    _attributions_for_payment, _entry_snapshot, eligible_service_amount, money, preview_payment_commission,
    validate_commission_entry_confirmation,
)
from services.finance_period_lock import ensure_profit_months_open

BUSINESS_TIME = ZoneInfo("Asia/Shanghai")
UNPAID = ("estimated", "pending_confirmation", "confirmed", "payable")


def _utc(now=None):
    value = now or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _month_start(month):
    if not re.fullmatch(r"(?!0000)\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise HTTPException(422, "账期必须为 YYYY-MM")
    return date.fromisoformat(month + "-01")


def _next_month(first):
    return (first.replace(day=28) + timedelta(days=4)).replace(day=1)


def _previous_month(first):
    return (first - timedelta(days=1)).strftime("%Y-%m")


async def statements_available(db):
    connection = await db.connection()
    return await connection.run_sync(lambda sync: inspect(sync).has_table("commission_statement_lines"))


async def lock_statements(db):
    # Every assignment and payout uses this same lock. SQLite ignores FOR UPDATE.
    if db.bind.dialect.name == "sqlite":
        await db.execute(text("UPDATE commission_statements SET id=id WHERE id < 0"))
    elif db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(2076408146)"))


async def assert_entry_outside_statement(db, entry_id, *, transition=None):
    if not await statements_available(db):
        return
    await lock_statements(db)
    owned = (await db.execute(select(CommissionEntry, CommissionStatement.paid_at)
        .join(CommissionStatementLine, CommissionStatementLine.entry_id == CommissionEntry.id)
        .join(CommissionStatement, CommissionStatement.id == CommissionStatementLine.statement_id)
        .where(CommissionEntry.id == entry_id).execution_options(populate_existing=True))).first()
    if not owned:
        return
    entry, paid_at = owned
    if paid_at is None and _entry_snapshot(entry).get("calculation_version") != "service_month_v2":
        # Historic recognized amounts can still follow the original payout path.
        # The shared transaction lock prevents an individual and a monthly double payment.
        if entry.status in ("confirmed", "payable") or transition == "reversed":
            return
    raise HTTPException(409, "这笔佣金已纳入月结单，请在对应结算单统一处理")


async def _receipt_issues(db, end, *, start=None, unassigned_only=False):
    # Match the accounting month used by the existing commission ledger.
    actual_day = func.coalesce(Payments.payment_date, Payments.created_at)
    query = select(Payments).where(actual_day < end, Payments.amount_paid > 0)
    if start is not None:
        query = query.where(actual_day >= start)
    if unassigned_only:
        # Filter in SQL before checking individual payments. The directory can be
        # opened many times a day, even when every receipt already has a channel.
        attribution = CustomerCommissionAttribution
        covered = select(attribution.id).where(
            attribution.customer_id == Payments.customer_id,
            attribution.effective_from <= func.date(actual_day),
            or_(attribution.effective_to.is_(None), attribution.effective_to >= func.date(actual_day)),
            or_(attribution.engagement_id.is_(None), attribution.engagement_id == Payments.engagement_id),
        )
        query = query.where(~covered.exists())
    recognized = select(CommissionEntry.id).where(
        CommissionEntry.payment_id == Payments.id, CommissionEntry.refund_id.is_(None),
        CommissionEntry.status.in_(("confirmed", "payable", "paid")),
    )
    payments = (await db.scalars(query.where(~recognized.exists()).order_by(Payments.id))).all()
    issues = []
    for payment in payments:
        if eligible_service_amount(payment) <= 0:
            continue
        owners = await _attributions_for_payment(db, payment)
        partner_id = owners[0].partner_id if owners else None
        if unassigned_only and partner_id is not None:
            continue
        preview = await preview_payment_commission(db, payment)
        problems = preview["issues"]
        if not problems and preview["segments"]:
            has_candidate = await db.scalar(select(CommissionEntry.id).where(
                CommissionEntry.payment_id == payment.id, CommissionEntry.refund_id.is_(None),
                CommissionEntry.partner_id == partner_id, CommissionEntry.status.in_(UNPAID),
            ).limit(1))
            if not has_candidate:
                problems = ["计佣明细尚未生成，请核对收款并扫描"]
        when = payment.payment_date or payment.created_at
        for problem in problems:
            issues.append({"description": f"收款 #{payment.id} · {problem}", "payment_id": payment.id,
                          "partner_id": partner_id, "currency": (payment.currency or "USD").upper(),
                          "source_month": when.strftime("%Y-%m")})
    return issues


async def _period(db, known, partner_id, currency, month, *, unpaid=False):
    while True:
        key = (partner_id, currency, month)
        period = known.get(key)
        if period is None:
            issued = _next_month(_month_start(month))
            period = CommissionStatement(partner_id=partner_id, month=month, currency=currency,
                                         issue_date=issued, due_date=issued.replace(day=15))
            db.add(period)
            await db.flush()
            known[key] = period
        if not unpaid or not period.paid_at:
            return period
        month = _next_month(_month_start(month)).strftime("%Y-%m")


def _guard_time(entry, days):
    if entry.entry_type == "first_order":
        return _utc(entry.occurred_at) + timedelta(days=days or 0)
    return None


def _eligible_month(source_month, guard, parent_due=None):
    due = _next_month(_month_start(source_month)).replace(day=15)
    if guard:
        guard_day = guard.astimezone(BUSINESS_TIME).date()
        if guard_day > due:
            due = guard_day.replace(day=15)
            if guard_day > due:
                due = _next_month(due).replace(day=15)
    if parent_due:
        due = max(due, parent_due)
    return _previous_month(due.replace(day=1))


async def reconcile_statements(db, *, now=None):
    """Materialize issued statements and reserve guarded lines once; caller commits."""
    await lock_statements(db)
    today = _utc(now).astimezone(BUSINESS_TIME).date()
    cutoff = today.replace(day=1)
    known = {(s.partner_id, s.currency, s.month): s for s in (await db.scalars(
        select(CommissionStatement).execution_options(populate_existing=True))).all()}
    by_id = {s.id: s for s in known.values()}
    assigned = {l.entry_id: l for l in (await db.scalars(select(CommissionStatementLine))).all()}
    query = select(CommissionEntry, CommissionAgreement.refund_guard_days).join(
        CommissionAgreement, CommissionAgreement.id == CommissionEntry.agreement_id,
    ).where(CommissionEntry.service_month < cutoff.strftime("%Y-%m"), CommissionEntry.status.in_(UNPAID)).order_by(
        CommissionEntry.refund_id.is_not(None), CommissionEntry.occurred_at, CommissionEntry.id,
    )
    rows = (await db.execute(query.execution_options(populate_existing=True))).all()
    due_for_entry = {}
    for entry, guard_days in rows:
        link = assigned.get(entry.id)
        if link and by_id[link.statement_id].paid_at:
            continue
        guard = _guard_time(entry, guard_days)
        target_month = _eligible_month(entry.service_month, guard, due_for_entry.get(entry.original_entry_id))
        origin = await _period(db, known, entry.partner_id, entry.currency, entry.service_month)
        period = await _period(db, known, entry.partner_id, entry.currency, target_month, unpaid=True)
        due_for_entry[entry.id] = period.due_date
        if link:
            link.statement_id, link.origin_statement_id = period.id, origin.id
        else:
            db.add(CommissionStatementLine(entry_id=entry.id, statement_id=period.id, origin_statement_id=origin.id))
    # A voided or manually paid historic item is never paid a second time.
    inactive = select(CommissionEntry.id).where(CommissionEntry.status.in_(("reversed", "paid")))
    open_periods = select(CommissionStatement.id).where(CommissionStatement.paid_at.is_(None))
    await db.execute(delete(CommissionStatementLine).where(
        CommissionStatementLine.entry_id.in_(inactive), CommissionStatementLine.statement_id.in_(open_periods),
    ))
    issues_by_period = defaultdict(list)
    for issue in await _receipt_issues(db, cutoff):
        if issue["partner_id"] is not None:
            period = await _period(db, known, issue["partner_id"], issue["currency"], issue["source_month"], unpaid=True)
            issues_by_period[period.id].append(issue)
    for period in known.values():
        if not period.paid_at:
            period.issues_json = json.dumps(issues_by_period[period.id], sort_keys=True, ensure_ascii=False)
    await db.flush()
    return {"issued_count": sum(s.issue_date <= today for s in known.values()), "eligible_entries": len(rows)}


async def _summaries(db, periods, now, *, detail=False):
    if not periods:
        return []
    ids = [s.id for s in periods]
    today = now.astimezone(BUSINESS_TIME).date()
    partners = {p.id: p for p in (await db.scalars(select(SalesPartner).where(
        SalesPartner.id.in_({s.partner_id for s in periods})))).all()}
    lines = (await db.execute(select(CommissionStatementLine, CommissionEntry, Customers.business_name,
                                     CommissionStatement.due_date, CommissionAgreement.refund_guard_days)
        .join(CommissionEntry, CommissionEntry.id == CommissionStatementLine.entry_id)
        .join(CommissionStatement, CommissionStatement.id == CommissionStatementLine.statement_id)
        .join(CommissionAgreement, CommissionAgreement.id == CommissionEntry.agreement_id)
        .outerjoin(Customers, Customers.id == CommissionEntry.customer_id)
        .where(or_(CommissionStatementLine.statement_id.in_(ids), CommissionStatementLine.origin_statement_id.in_(ids)),
               CommissionEntry.status != "reversed",
               or_(CommissionEntry.status != "paid", CommissionStatement.paid_at.is_not(None)))
        .order_by(CommissionEntry.occurred_at, CommissionEntry.id)
        .execution_options(populate_existing=True))).all()
    ledger_months = {row[1].service_month for row in lines}
    closed_query = select(MonthlyProfitClose.year_month).where(
        MonthlyProfitClose.status == "locked", MonthlyProfitClose.year_month.in_(ledger_months),
    )
    closed = set((await db.scalars(closed_query)).all())
    current, deferred = defaultdict(list), defaultdict(list)
    for row in lines:
        link = row[0]
        current[link.statement_id].append(row)
        if link.origin_statement_id != link.statement_id:
            deferred[link.origin_statement_id].append(row)

    def entry_info(row):
        _, e, customer_name, due_date, _ = row
        return dict(entry_id=e.id, customer_id=e.customer_id, customer_name=customer_name, payment_id=e.payment_id,
                    refund_id=e.refund_id, entry_type=e.entry_type, source_month=e.service_month, due_date=due_date,
                    eligible_service_amount=e.eligible_service_amount, commission_amount=e.commission_amount,
                    contract_rate=e.contract_rate, status=e.status)

    result = []
    for s in periods:
        if s.paid_at and s.paid_snapshot_json:
            frozen = json.loads(s.paid_snapshot_json)
            if not detail:
                frozen.pop("entries", None)
                frozen.pop("deferred_entries", None)
            result.append(frozen)
            continue
        entries = current[s.id]
        later = deferred[s.id]
        quality = json.loads(s.issues_json or "[]")
        issues = list(dict.fromkeys(i["description"] for i in quality))
        partner = partners[s.partner_id]
        total = money(sum(row[1].commission_amount for row in entries))
        blocked_until = None
        for _, e, _, _, guard_days in entries:
            if e.status in ("pending_confirmation", "estimated"):
                if e.service_month in closed:
                    issues.append(f"{e.service_month} 已关账，需核对尚未确认佣金")
                if e.status == "estimated" or _entry_snapshot(e).get("calculation_version") != "service_month_v2":
                    issues.append(f"佣金 #{e.id} 的历史计佣规则待核对")
                guard = _guard_time(e, guard_days)
                if guard and guard > now:
                    blocked_until = max(blocked_until or guard, guard)
        if entries and partner.status == "suspended":
            issues.append("渠道已暂停结算")
        if entries and total <= 0:
            issues.append("本期净佣金不大于零，请核对抵扣或退款处理")
        issues = list(dict.fromkeys(issues))
        if s.paid_at:
            status = "paid"
            total = s.paid_amount
            issues = []
        elif issues:
            status = "needs_review"
        elif today < s.due_date or blocked_until or not entries:
            status = "scheduled"
        else:
            status = "ready"
        # A stale form may not post a changed amount or changed line composition.
        content = [(e.id, e.status, e.commission_amount, e.contract_rate, e.eligible_service_amount,
                    e.agreement_id, e.attribution_id, e.snapshot_json) for _, e, *_ in entries]
        revision = hashlib.sha256(json.dumps([s.id, content, issues], sort_keys=True).encode()).hexdigest()
        row = dict(id=s.id, month=s.month, partner_id=s.partner_id, partner_name=partner.name,
                   currency=s.currency, issue_date=s.issue_date, due_date=s.due_date, status=status,
                   total_amount=total, entry_count=len(entries), deferred_count=len(later),
                   deferred_amount=money(sum(r[1].commission_amount for r in later)), issues=issues,
                   payout_reference=s.payout_reference, paid_at=s.paid_at, revision=revision)
        if detail:
            row["entries"] = [entry_info(r) for r in entries]
            row["deferred_entries"] = [entry_info(r) for r in later]
        result.append(row)
    return result


async def list_statements(db, month, *, partner_id=None, now=None):
    clock = _utc(now)
    start = _month_start(month)
    query = select(CommissionStatement).where(CommissionStatement.month == month,
        CommissionStatement.issue_date <= clock.astimezone(BUSINESS_TIME).date())
    if partner_id is not None:
        query = query.where(CommissionStatement.partner_id == partner_id)
    periods = list((await db.scalars(query.order_by(CommissionStatement.partner_id, CommissionStatement.currency))).all())
    unmatched = []
    if partner_id is None and _next_month(start) <= clock.astimezone(BUSINESS_TIME).date():
        unmatched = await _receipt_issues(db, _next_month(start), start=start, unassigned_only=True)
    items = [row for row in await _summaries(db, periods, clock) if _has_statement_activity(row)]
    return {"month": month, "items": items, "issues": unmatched}


def _has_statement_activity(row):
    return row["status"] == "paid" or bool(row["entry_count"] or row["deferred_count"] or row["issues"])


async def get_statement(db, statement_id, *, now=None):
    clock = _utc(now)
    period = await db.get(CommissionStatement, statement_id)
    if not period or period.issue_date > clock.astimezone(BUSINESS_TIME).date():
        raise HTTPException(404, "月结单尚未出具或不存在")
    result = (await _summaries(db, [period], clock, detail=True))[0]
    if not _has_statement_activity(result):
        raise HTTPException(410, "本期可结算明细已全部移除或单独处理，当前没有待付月结单")
    return result


async def statement_reminders(db, *, now=None):
    clock = _utc(now)
    periods = (await db.scalars(select(CommissionStatement).where(
        CommissionStatement.paid_at.is_(None), CommissionStatement.due_date <= clock.astimezone(BUSINESS_TIME).date(),
    ).order_by(CommissionStatement.month))).all()
    summary = defaultdict(lambda: {"ready_count": 0, "review_count": 0})
    for row in await _summaries(db, periods, clock):
        if row["status"] in ("ready", "needs_review"):
            key = "ready_count" if row["status"] == "ready" else "review_count"
            summary[row["month"]][key] += 1
    return {"items": [{"month": month, **counts} for month, counts in summary.items()]}


async def settle_statement(db, statement_id, *, payout_reference, expected_total, expected_entry_count,
                           revision, actor_id, actor_name, now=None):
    clock = _utc(now)
    reference = str(payout_reference or "").strip()
    if not reference or len(reference) > 160:
        raise HTTPException(422, "请输入不超过 160 字的实际付款流水或凭证")
    await lock_statements(db)
    async with db.begin_nested():
        period = await db.scalar(select(CommissionStatement).where(CommissionStatement.id == statement_id)
                                 .with_for_update().execution_options(populate_existing=True))
        if not period or period.issue_date > clock.astimezone(BUSINESS_TIME).date():
            raise HTTPException(404, "月结单尚未出具或不存在")
        if period.paid_at:
            if period.payout_reference != reference:
                raise HTTPException(409, "本期已结算，付款凭证与已有记录不同")
            return await get_statement(db, statement_id, now=clock)
        used_by = await db.scalar(select(CommissionStatement.id).where(CommissionStatement.payout_reference == reference))
        if used_by:
            raise HTTPException(409, f"此付款凭证已登记在月结单 #{used_by}")
        await reconcile_statements(db, now=clock)
        owned = select(CommissionStatementLine.entry_id).where(CommissionStatementLine.statement_id == statement_id)
        sources = list((await db.execute(select(CommissionEntry.customer_id, CommissionEntry.payment_id)
                                         .where(CommissionEntry.id.in_(owned)))).all())
        # Same lock order as scanner, customer transfer and individual ledger actions.
        for model, identifiers in ((Customers, {r.customer_id for r in sources}), (Payments, {r.payment_id for r in sources})):
            if identifiers:
                await db.execute(select(model.id).where(model.id.in_(identifiers)).order_by(model.id).with_for_update())
        entries = list((await db.scalars(select(CommissionEntry).where(CommissionEntry.id.in_(owned))
            .order_by(CommissionEntry.refund_id.is_not(None), CommissionEntry.id)
            .with_for_update().execution_options(populate_existing=True))).all())
        current = await get_statement(db, statement_id, now=clock)
        if current["status"] != "ready":
            raise HTTPException(409, "；".join(current["issues"]) or "当前未到结算日或没有可登记的佣金")
        if (current["revision"] != revision or current["entry_count"] != expected_entry_count
                or current["total_amount"] != expected_total):
            raise HTTPException(409, "本期金额或明细已变化，请刷新核对后再登记")
        for entry in entries:
            if entry.status == "pending_confirmation":
                try:
                    await validate_commission_entry_confirmation(db, entry)
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
                await ensure_profit_months_open(db, [entry.occurred_at, entry.service_month], action="确认月结佣金")
                sequence = ("confirmed", "payable", "paid")
            elif entry.status == "confirmed":
                sequence = ("payable", "paid")
            elif entry.status == "payable":
                sequence = ("paid",)
            else:
                raise HTTPException(409, f"佣金 #{entry.id} 状态已变化，请刷新核对")
            for state in sequence:
                db.add(CommissionStatusEvent(commission_entry_id=entry.id, from_status=entry.status, to_status=state,
                    actor_id=str(actor_id), actor_name=actor_name, reason=f"月结单 #{period.id} · {reference}"))
                entry.status = state
                setattr(entry, {"confirmed":"confirmed_at","payable":"payable_at","paid":"paid_at"}[state], clock)
            entry.payout_reference = reference
            await db.flush()
        period.paid_at, period.paid_amount, period.payout_reference = clock, current["total_amount"], reference
        period.paid_by_id, period.paid_by_name = str(actor_id), actor_name
        await db.flush()
        final = await get_statement(db, statement_id, now=clock)
        period.paid_snapshot_json = json.dumps(final, default=lambda d: d.isoformat(), sort_keys=True, ensure_ascii=False)
        await db.flush()
        return json.loads(period.paid_snapshot_json)
