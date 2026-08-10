from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.customer_lifecycles import CustomerLifecycleCycle, CustomerLifecycleEvent
from models.customers import Customers
from models.management_decisions import CustomerEngagement, EngagementLifecycleEvent
from models.payments import Payments
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from models.subscriptions import Subscriptions


ACTIVE_LIFECYCLE_STATUSES = {"active", "paused", "pending_stop"}
ACTIVE_ENGAGEMENT_STATUSES = {"pending_setup", "trial", "active_paid", "at_risk", "paused", "pending_stop", "reactivated"}
CLOSABLE_SUBSCRIPTION_STATUSES = {"active", "expiring_soon", "renewal_pending", "paused"}
OPEN_SERVICE_TASK_STATUSES = {"pending", "in_progress", "waiting_client", "internal_waiting", "delayed"}
STOP_REASONS = {
    "performance": "效果不满意",
    "price": "价格问题",
    "service": "服务问题",
    "closed_business": "客户关店",
    "business_difficulty": "客户经营困难",
    "changed_provider": "更换服务商",
    "seasonal_pause": "季节性暂停",
    "payment": "付款问题",
    "owner_change": "老板变更",
    "data_correction": "历史数据修正",
    "other": "其他",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def month_floor(value: datetime) -> datetime:
    value = ensure_aware(value)
    return datetime(value.year, value.month, 1, tzinfo=timezone.utc)


def add_months(value: datetime, months: int) -> datetime:
    value = ensure_aware(value)
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def months_between(started_at: datetime, ended_at: datetime) -> float:
    seconds = max((ensure_aware(ended_at) - ensure_aware(started_at)).total_seconds(), 0)
    return round(seconds / (86400 * 30.4375), 1)


def _cycle_dict(cycle: CustomerLifecycleCycle) -> dict[str, Any]:
    return {
        "id": cycle.id,
        "customer_id": cycle.customer_id,
        "cycle_number": cycle.cycle_number,
        "first_payment_id": cycle.first_payment_id,
        "started_at": cycle.started_at,
        "ended_at": cycle.ended_at,
        "status": cycle.status,
        "start_source": cycle.start_source,
        "start_locked": bool(cycle.start_locked),
        "stop_reason": cycle.stop_reason,
        "stop_reason_label": STOP_REASONS.get(cycle.stop_reason or "", cycle.stop_reason),
        "stop_note": cycle.stop_note,
        "confirmed_by_name": cycle.confirmed_by_name,
        "created_at": cycle.created_at,
        "updated_at": cycle.updated_at,
    }


async def close_related_customer_records(
    db: AsyncSession,
    *,
    customer_id: int,
    effective_at: datetime,
    reason_code: Optional[str],
    note: Optional[str],
    actor_id: str,
    actor_name: str,
    lifecycle_cycle_id: int,
) -> dict[str, int]:
    """Stop active projects, renewals and delivery work without deleting history."""
    effective_at = ensure_aware(effective_at)
    now = utcnow()
    projects = list((await db.execute(
        select(CustomerEngagement).where(CustomerEngagement.customer_id == customer_id)
    )).scalars().all())
    stopped_project_count = 0
    for project in projects:
        if project.status not in ACTIVE_ENGAGEMENT_STATUSES:
            continue
        previous_status = project.status
        project.status = "stopped"
        project.stopped_at = effective_at
        project.paused_at = None
        project.stop_reason_code = reason_code
        project.stop_note = note
        event_key = f"customer-stop:{lifecycle_cycle_id}:{project.id}"
        existing_event = (await db.execute(
            select(EngagementLifecycleEvent).where(EngagementLifecycleEvent.idempotency_key == event_key)
        )).scalar_one_or_none()
        if not existing_event:
            db.add(EngagementLifecycleEvent(
                engagement_id=project.id,
                event_type="status_changed",
                effective_at=effective_at,
                reason_code=reason_code,
                idempotency_key=event_key,
                actor_id=actor_id,
                actor_name=actor_name,
                note=f"{previous_status} -> stopped；客户整体停止合作" + (f"；{note}" if note else ""),
            ))
        stopped_project_count += 1

    subscriptions = list((await db.execute(
        select(Subscriptions).where(Subscriptions.customer_id == customer_id)
    )).scalars().all())
    stopped_subscription_count = 0
    for subscription in subscriptions:
        status = str(subscription.status or "").lower()
        next_payment_at = ensure_aware(subscription.next_payment_date) if subscription.next_payment_date else None
        has_future_collection = bool(next_payment_at and next_payment_at >= effective_at)
        if status not in CLOSABLE_SUBSCRIPTION_STATUSES and not subscription.auto_renew and not has_future_collection:
            continue
        subscription.status = "stopped"
        subscription.auto_renew = False
        subscription.next_payment_date = None
        subscription.updated_at = now
        stopped_subscription_count += 1

    # Delivery rows are historical operating records, so keep them and mark
    # them ended instead of deleting them. This prevents a lost customer from
    # continuing to appear as an active onboarding/operations client.
    progresses = list((await db.execute(
        select(Service_progresses).where(Service_progresses.customer_id == customer_id)
    )).scalars().all())
    ended_service_count = 0
    for progress in progresses:
        if str(progress.service_stage or "").lower() == "ended":
            continue
        progress.service_stage = "ended"
        progress.progress_percent = 100
        progress.service_end_date = effective_at.date().isoformat()
        progress.last_update_time = now.isoformat()
        progress.last_update_person = actor_name
        progress.last_work_summary = "客户停止合作，服务记录已自动归档"
        progress.issue_resolved = True
        progress.issue_resolved_date = effective_at.date().isoformat()
        ended_service_count += 1

    service_tasks = list((await db.execute(
        select(Service_tasks).where(Service_tasks.customer_id == customer_id)
    )).scalars().all())
    cancelled_service_task_count = 0
    for task in service_tasks:
        if str(task.status or "").lower() not in OPEN_SERVICE_TASK_STATUSES:
            continue
        task.status = "cancelled"
        task.completed_date = effective_at.date().isoformat()
        task.completed_at = now.isoformat()
        task.completed_by = actor_name
        task.completion_note = "客户停止合作，未完成交付任务自动取消并保留历史"
        cancelled_service_task_count += 1

    return {
        "stopped_projects": stopped_project_count,
        "stopped_subscriptions": stopped_subscription_count,
        "ended_services": ended_service_count,
        "cancelled_service_tasks": cancelled_service_task_count,
    }


async def sync_lifecycle_from_payments(
    db: AsyncSession,
    customer_ids: Optional[Iterable[int]] = None,
) -> dict[str, int]:
    """Materialize the first valid positive payment as lifecycle cycle one.

    A package expiry never closes the cycle. Stopped customers are not
    automatically reactivated because a late settlement can arrive after stop.
    """
    wanted = {int(value) for value in customer_ids or []}
    payment_query = (
        select(Payments)
        .where(Payments.amount_paid > 0, Payments.payment_date.is_not(None))
        .order_by(Payments.customer_id.asc(), Payments.payment_date.asc(), Payments.id.asc())
    )
    if wanted:
        payment_query = payment_query.where(Payments.customer_id.in_(wanted))
    payments = (await db.execute(payment_query)).scalars().all()

    first_by_customer: dict[int, Payments] = {}
    for payment in payments:
        first_by_customer.setdefault(int(payment.customer_id), payment)
    removed = 0
    no_payment_ids = wanted - set(first_by_customer)
    if no_payment_ids:
        removable = (
            await db.execute(
                select(CustomerLifecycleCycle).where(
                    CustomerLifecycleCycle.customer_id.in_(no_payment_ids),
                    CustomerLifecycleCycle.cycle_number == 1,
                    CustomerLifecycleCycle.start_locked.is_(False),
                    CustomerLifecycleCycle.status != "stopped",
                )
            )
        ).scalars().all()
        for cycle in removable:
            await db.execute(delete(CustomerLifecycleEvent).where(CustomerLifecycleEvent.cycle_id == cycle.id))
            await db.delete(cycle)
            removed += 1
        if removed:
            await db.commit()
    if not first_by_customer:
        return {"created": 0, "updated": 0, "review": 0, "removed": removed}

    customers = (
        await db.execute(select(Customers).where(Customers.id.in_(list(first_by_customer))))
    ).scalars().all()
    customer_map = {int(customer.id): customer for customer in customers}
    existing = (
        await db.execute(
            select(CustomerLifecycleCycle).where(
                CustomerLifecycleCycle.customer_id.in_(list(first_by_customer)),
                CustomerLifecycleCycle.cycle_number == 1,
            )
        )
    ).scalars().all()
    cycle_map = {int(cycle.customer_id): cycle for cycle in existing}
    now = utcnow()
    created = updated = review = 0

    for customer_id, payment in first_by_customer.items():
        customer = customer_map.get(customer_id)
        if not customer:
            continue
        payment_at = ensure_aware(payment.payment_date)
        cycle = cycle_map.get(customer_id)
        if not cycle:
            customer_status = str(customer.status or "").lower()
            lifecycle_status = "paused" if customer_status == "paused" else "active"
            if customer_status == "lost":
                lifecycle_status = "pending_stop"
                review += 1
            cycle = CustomerLifecycleCycle(
                customer_id=customer_id,
                cycle_number=1,
                first_payment_id=payment.id,
                started_at=payment_at,
                status=lifecycle_status,
                start_source="payment",
                start_locked=False,
                created_at=now,
                updated_at=now,
            )
            db.add(cycle)
            await db.flush()
            db.add(
                CustomerLifecycleEvent(
                    customer_id=customer_id,
                    cycle_id=cycle.id,
                    event_type="started",
                    effective_at=payment_at,
                    source_type="payment",
                    source_id=payment.id,
                    note="系统根据第一笔有效记账建立合作周期",
                    actor_name="系统",
                    created_at=now,
                )
            )
            cycle_map[customer_id] = cycle
            created += 1
            continue

        if cycle.start_locked or cycle.start_source == "manual":
            continue
        if cycle.ended_at and payment_at > ensure_aware(cycle.ended_at):
            # A late settlement after stop is not a valid replacement for the
            # original cooperation start. Keep the historical cycle unchanged;
            # the overview will flag the source mismatch for manual review.
            continue
        if cycle.first_payment_id != payment.id or ensure_aware(cycle.started_at) != payment_at:
            cycle.first_payment_id = payment.id
            cycle.started_at = payment_at
            cycle.updated_at = now
            updated += 1

    await db.commit()
    return {"created": created, "updated": updated, "review": review, "removed": removed}


async def _load_cycles(db: AsyncSession) -> list[CustomerLifecycleCycle]:
    return (
        await db.execute(
            select(CustomerLifecycleCycle).order_by(
                CustomerLifecycleCycle.started_at.asc(), CustomerLifecycleCycle.id.asc()
            )
        )
    ).scalars().all()


def _kaplan_meier_median_months(cycles: list[CustomerLifecycleCycle], as_of: datetime) -> Optional[float]:
    observations: list[tuple[float, bool]] = []
    for cycle in cycles:
        end = ensure_aware(cycle.ended_at) if cycle.ended_at else as_of
        observations.append((max((end - ensure_aware(cycle.started_at)).total_seconds(), 0), bool(cycle.ended_at)))
    if not observations:
        return None
    at_risk = len(observations)
    survival = 1.0
    for duration in sorted({value for value, _event in observations}):
        deaths = sum(1 for value, event in observations if event and value == duration)
        censored = sum(1 for value, event in observations if not event and value == duration)
        if at_risk > 0 and deaths:
            survival *= 1 - deaths / at_risk
            if survival <= 0.5:
                return round(duration / (86400 * 30.4375), 1)
        at_risk -= deaths + censored
    return None


def _retention_rate(cycles: list[CustomerLifecycleCycle], months: int, as_of: datetime) -> Optional[float]:
    eligible = [cycle for cycle in cycles if add_months(ensure_aware(cycle.started_at), months) <= as_of]
    if not eligible:
        return None
    retained = sum(
        1
        for cycle in eligible
        if not cycle.ended_at or ensure_aware(cycle.ended_at) >= add_months(ensure_aware(cycle.started_at), months)
    )
    return round(retained * 100 / len(eligible), 1)


async def lifecycle_overview(db: AsyncSession, start_date: datetime, as_of: datetime) -> dict[str, Any]:
    await sync_lifecycle_from_payments(db)
    start_date = ensure_aware(start_date)
    as_of = ensure_aware(as_of)
    cycles = await _load_cycles(db)
    customers = (await db.execute(select(Customers))).scalars().all()
    customer_map = {int(customer.id): customer for customer in customers}
    first_payment_ids = {int(c.first_payment_id) for c in cycles if c.first_payment_id}
    first_payments = (
        await db.execute(select(Payments).where(Payments.id.in_(first_payment_ids)))
    ).scalars().all() if first_payment_ids else []
    first_payment_map = {int(payment.id): payment for payment in first_payments}
    projects = (await db.execute(select(CustomerEngagement))).scalars().all()
    subscriptions = (await db.execute(select(Subscriptions))).scalars().all()
    service_progresses = (await db.execute(select(Service_progresses))).scalars().all()
    service_tasks = (await db.execute(select(Service_tasks))).scalars().all()
    active_projects_by_customer = Counter(
        int(row.customer_id) for row in projects if row.status in ACTIVE_ENGAGEMENT_STATUSES
    )
    active_subscriptions_by_customer = Counter()
    for row in subscriptions:
        status = str(row.status or "").lower()
        if status in CLOSABLE_SUBSCRIPTION_STATUSES or bool(row.auto_renew) or bool(row.next_payment_date):
            active_subscriptions_by_customer[int(row.customer_id)] += 1
    active_services_by_customer = Counter(
        int(row.customer_id)
        for row in service_progresses
        if str(row.service_stage or "").lower() not in {"ended", "paused"}
    )
    active_service_tasks_by_customer = Counter(
        int(row.customer_id)
        for row in service_tasks
        if str(row.status or "").lower() in OPEN_SERVICE_TASK_STATUSES
    )

    in_window = [
        cycle for cycle in cycles
        if ensure_aware(cycle.started_at) <= as_of
        and (not cycle.ended_at or ensure_aware(cycle.ended_at) >= start_date)
    ]
    new_cycles = [cycle for cycle in cycles if start_date <= ensure_aware(cycle.started_at) <= as_of]
    new_customer_cycles = [cycle for cycle in new_cycles if cycle.cycle_number == 1]
    existing_at_start = [
        cycle for cycle in cycles
        if ensure_aware(cycle.started_at) < start_date
        and (not cycle.ended_at or ensure_aware(cycle.ended_at) >= start_date)
    ]
    current_cycles = [
        cycle for cycle in in_window
        if ensure_aware(cycle.started_at) <= as_of
        and (not cycle.ended_at or ensure_aware(cycle.ended_at) > as_of)
    ]
    stopped_in_window = [
        cycle for cycle in cycles
        if cycle.ended_at and start_date <= ensure_aware(cycle.ended_at) <= as_of
    ]

    stopped_durations = [months_between(c.started_at, c.ended_at) for c in stopped_in_window if c.ended_at]
    reason_counts = Counter(c.stop_reason or "other" for c in stopped_in_window)

    latest_by_customer: dict[int, CustomerLifecycleCycle] = {}
    for cycle in cycles:
        current = latest_by_customer.get(int(cycle.customer_id))
        if not current or cycle.cycle_number > current.cycle_number:
            latest_by_customer[int(cycle.customer_id)] = cycle
    customer_rows = []
    for customer_id, cycle in latest_by_customer.items():
        customer = customer_map.get(customer_id)
        if (
            not customer
            or ensure_aware(cycle.started_at) > as_of
            or (cycle.ended_at and ensure_aware(cycle.ended_at) < start_date)
        ):
            continue
        duration_end = ensure_aware(cycle.ended_at) if cycle.ended_at else as_of
        source_payment = first_payment_map.get(int(cycle.first_payment_id)) if cycle.first_payment_id else None
        payment_source_mismatch = bool(
            cycle.first_payment_id
            and (
                not source_payment
                or source_payment.amount_paid <= 0
                or not source_payment.payment_date
                or ensure_aware(source_payment.payment_date) != ensure_aware(cycle.started_at)
            )
        )
        closure_counts = {
            "projects": active_projects_by_customer.get(customer_id, 0),
            "subscriptions": active_subscriptions_by_customer.get(customer_id, 0),
            "services": active_services_by_customer.get(customer_id, 0),
            "service_tasks": active_service_tasks_by_customer.get(customer_id, 0),
        }
        closure_needed = cycle.status == "stopped" and any(closure_counts.values())
        customer_rows.append({
            **_cycle_dict(cycle),
            "business_name": customer.business_name,
            "customer_code": customer.customer_code,
            "source": customer.source,
            "sales_person": customer.sales_person,
            "customer_status": customer.status,
            "cooperation_months": months_between(cycle.started_at, duration_end),
            "closure_needed": closure_needed,
            "closure_open_counts": closure_counts,
            "needs_review": (
                cycle.status == "pending_stop"
                or closure_needed
                or payment_source_mismatch
                or (not cycle.first_payment_id and not cycle.start_locked)
                or bool(cycle.ended_at and ensure_aware(cycle.ended_at) < ensure_aware(cycle.started_at))
            ),
        })
    customer_rows.sort(key=lambda item: (item["needs_review"], item["started_at"]), reverse=True)

    monthly_rows = []
    cursor = month_floor(start_date)
    while cursor <= as_of:
        next_month = add_months(cursor, 1)
        active_at_start = sum(
            1 for c in cycles
            if ensure_aware(c.started_at) < cursor
            and (not c.ended_at or ensure_aware(c.ended_at) >= cursor)
        )
        started = sum(1 for c in cycles if cursor <= ensure_aware(c.started_at) < next_month)
        stopped = sum(
            1 for c in cycles
            if c.ended_at and cursor <= ensure_aware(c.ended_at) < next_month
        )
        monthly_rows.append({
            "month": cursor.strftime("%Y-%m"),
            "active_at_start": active_at_start,
            "started": started,
            "stopped": stopped,
            "churn_rate": round(stopped * 100 / active_at_start, 1) if active_at_start else 0.0,
        })
        cursor = next_month

    cohort_groups: dict[str, list[CustomerLifecycleCycle]] = defaultdict(list)
    for cycle in new_customer_cycles:
        cohort_groups[ensure_aware(cycle.started_at).strftime("%Y-%m")].append(cycle)
    cohort_rows = []
    for month, cohort in sorted(cohort_groups.items()):
        cohort_rows.append({
            "month": month,
            "customers": len(cohort),
            "m1": _retention_rate(cohort, 1, as_of),
            "m3": _retention_rate(cohort, 3, as_of),
            "m6": _retention_rate(cohort, 6, as_of),
            "m12": _retention_rate(cohort, 12, as_of),
        })

    return {
        "period": {"start_date": start_date, "as_of": as_of},
        "summary": {
            "new_customers": len({c.customer_id for c in new_customer_cycles}),
            "existing_customers": len({c.customer_id for c in existing_at_start}),
            "current_active": sum(1 for c in current_cycles if c.status == "active"),
            "current_paused": sum(1 for c in current_cycles if c.status == "paused"),
            "pending_stop": sum(1 for c in current_cycles if c.status == "pending_stop"),
            "stopped": len(stopped_in_window),
            "retention_3m": _retention_rate(new_customer_cycles, 3, as_of),
            "retention_6m": _retention_rate(new_customer_cycles, 6, as_of),
            "retention_12m": _retention_rate(new_customer_cycles, 12, as_of),
            "median_tenure_months": _kaplan_meier_median_months(new_customer_cycles, as_of),
            "average_stopped_months": round(sum(stopped_durations) / len(stopped_durations), 1) if stopped_durations else None,
            "review_count": sum(1 for row in customer_rows if row["needs_review"]),
        },
        "monthly": monthly_rows,
        "cohorts": cohort_rows,
        "stop_reasons": [
            {"reason": reason, "label": STOP_REASONS.get(reason, reason), "count": count}
            for reason, count in reason_counts.most_common()
        ],
        "customers": customer_rows,
    }


async def customer_lifecycle_detail(db: AsyncSession, customer_id: int) -> dict[str, Any]:
    await sync_lifecycle_from_payments(db, [customer_id])
    customer = (await db.execute(select(Customers).where(Customers.id == customer_id))).scalar_one_or_none()
    if not customer:
        raise ValueError("Customer not found")
    cycles = (
        await db.execute(
            select(CustomerLifecycleCycle)
            .where(CustomerLifecycleCycle.customer_id == customer_id)
            .order_by(CustomerLifecycleCycle.cycle_number.desc())
        )
    ).scalars().all()
    events = (
        await db.execute(
            select(CustomerLifecycleEvent)
            .where(CustomerLifecycleEvent.customer_id == customer_id)
            .order_by(CustomerLifecycleEvent.effective_at.desc(), CustomerLifecycleEvent.id.desc())
        )
    ).scalars().all()
    return {
        "customer": {"id": customer.id, "business_name": customer.business_name, "customer_code": customer.customer_code},
        "cycles": [_cycle_dict(cycle) for cycle in cycles],
        "events": [
            {
                "id": event.id,
                "cycle_id": event.cycle_id,
                "event_type": event.event_type,
                "effective_at": event.effective_at,
                "source_type": event.source_type,
                "source_id": event.source_id,
                "reason_code": event.reason_code,
                "reason_label": STOP_REASONS.get(event.reason_code or "", event.reason_code),
                "note": event.note,
                "actor_name": event.actor_name,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


async def apply_lifecycle_action(
    db: AsyncSession,
    customer_id: int,
    action: str,
    effective_at: datetime,
    actor_id: str,
    actor_name: str,
    reason_code: Optional[str] = None,
    note: Optional[str] = None,
    first_payment_id: Optional[int] = None,
) -> dict[str, Any]:
    await sync_lifecycle_from_payments(db, [customer_id])
    customer = (await db.execute(select(Customers).where(Customers.id == customer_id))).scalar_one_or_none()
    if not customer:
        raise ValueError("Customer not found")
    cycle = (
        await db.execute(
            select(CustomerLifecycleCycle)
            .where(CustomerLifecycleCycle.customer_id == customer_id)
            .order_by(CustomerLifecycleCycle.cycle_number.desc())
        )
    ).scalars().first()
    if not cycle:
        raise ValueError("该客户还没有有效收款，无法建立合作周期")
    effective_at = ensure_aware(effective_at)
    now = utcnow()
    event_type = action
    source_type = "manual"
    source_id = None

    if action in {"pause", "pending_stop", "resume", "stop"}:
        if effective_at.date() < ensure_aware(cycle.started_at).date() or effective_at.date() > now.date():
            raise ValueError("生效日期必须在合作开始日期和当前时间之间")

    if action == "adjust_start":
        upper_date = (ensure_aware(cycle.ended_at) if cycle.ended_at else now).date()
        if effective_at.date() > upper_date:
            raise ValueError("合作开始日期不能晚于停止日期或当前时间")
        previous_started_at = ensure_aware(cycle.started_at)
        previous_payment_id = cycle.first_payment_id
        if first_payment_id:
            payment = (
                await db.execute(
                    select(Payments).where(
                        Payments.id == first_payment_id,
                        Payments.customer_id == customer_id,
                        Payments.amount_paid > 0,
                    )
                )
            ).scalar_one_or_none()
            if not payment:
                raise ValueError("指定的有效记账记录不存在")
            source_type, source_id = "payment", payment.id
        cycle.started_at = effective_at
        cycle.first_payment_id = first_payment_id
        cycle.start_source = "manual"
        cycle.start_locked = True
        audit_summary = (
            f"原开始日期 {previous_started_at.date().isoformat()}"
            f"（记账 #{previous_payment_id or '人工'}）调整为 {effective_at.date().isoformat()}"
            f"（记账 #{first_payment_id or '人工'}）"
        )
        note = f"{audit_summary}；{note}" if note else audit_summary
    elif action == "pause":
        if cycle.status != "active":
            raise ValueError("只有合作中的客户可以暂停")
        cycle.status = "paused"
        customer.status = "paused"
    elif action == "pending_stop":
        if cycle.status not in {"active", "paused"}:
            raise ValueError("当前状态不能进入待确认停止")
        cycle.status = "pending_stop"
    elif action == "resume":
        if cycle.status not in {"paused", "pending_stop"}:
            raise ValueError("只有暂停或待确认停止的客户可以恢复")
        cycle.status = "active"
        customer.status = "closed"
    elif action == "stop":
        if cycle.status not in ACTIVE_LIFECYCLE_STATUSES:
            raise ValueError("该合作周期已经停止")
        if not reason_code or reason_code not in STOP_REASONS:
            raise ValueError("请选择停止合作原因")
        cycle.status = "stopped"
        cycle.ended_at = effective_at
        cycle.stop_reason = reason_code
        cycle.stop_note = note
        cycle.confirmed_by_id = actor_id
        cycle.confirmed_by_name = actor_name
        customer.status = "lost"
        closure_summary = await close_related_customer_records(
            db,
            customer_id=customer_id,
            effective_at=effective_at,
            reason_code=reason_code,
            note=note,
            actor_id=actor_id,
            actor_name=actor_name,
            lifecycle_cycle_id=cycle.id,
        )
    elif action == "reactivate":
        if cycle.status != "stopped" or not cycle.ended_at:
            raise ValueError("只有已停止合作的客户可以重新合作")
        payment_query = (
            select(Payments)
            .where(
                Payments.customer_id == customer_id,
                Payments.amount_paid > 0,
                Payments.payment_date.is_not(None),
                Payments.payment_date > cycle.ended_at,
            )
            .order_by(Payments.payment_date.asc(), Payments.id.asc())
        )
        payment = (await db.execute(payment_query)).scalars().first()
        if not payment:
            raise ValueError("停止合作后还没有新的有效收款，请先录入收款")
        cycle = CustomerLifecycleCycle(
            customer_id=customer_id,
            cycle_number=cycle.cycle_number + 1,
            first_payment_id=payment.id,
            started_at=ensure_aware(payment.payment_date),
            status="active",
            start_source="payment",
            start_locked=False,
            created_at=now,
            updated_at=now,
        )
        db.add(cycle)
        await db.flush()
        effective_at = ensure_aware(payment.payment_date)
        source_type, source_id = "payment", payment.id
        customer.status = "closed"
    else:
        raise ValueError("Unsupported lifecycle action")

    cycle.updated_at = now
    db.add(
        CustomerLifecycleEvent(
            customer_id=customer_id,
            cycle_id=cycle.id,
            event_type=event_type,
            effective_at=effective_at,
            source_type=source_type,
            source_id=source_id,
            reason_code=reason_code,
            note=note,
            actor_id=actor_id,
            actor_name=actor_name,
            created_at=now,
        )
    )
    await db.commit()
    await db.refresh(cycle)
    payload = _cycle_dict(cycle)
    if action == "stop":
        payload["closure_summary"] = closure_summary
    return payload


async def reconcile_stopped_customer(
    db: AsyncSession,
    *,
    customer_id: int,
    actor_id: str,
    actor_name: str,
) -> dict[str, Any]:
    """Repair older stopped customers whose project or renewal status stayed active."""
    customer = (await db.execute(select(Customers).where(Customers.id == customer_id))).scalar_one_or_none()
    if not customer:
        raise ValueError("Customer not found")
    cycle = (
        await db.execute(
            select(CustomerLifecycleCycle)
            .where(CustomerLifecycleCycle.customer_id == customer_id)
            .order_by(CustomerLifecycleCycle.cycle_number.desc())
        )
    ).scalars().first()
    if not cycle or cycle.status != "stopped" or not cycle.ended_at:
        raise ValueError("只有已停止合作的客户可以同步闭环")
    customer.status = "lost"
    summary = await close_related_customer_records(
        db,
        customer_id=customer_id,
        effective_at=cycle.ended_at,
        reason_code=cycle.stop_reason,
        note=cycle.stop_note,
        actor_id=actor_id,
        actor_name=actor_name,
        lifecycle_cycle_id=cycle.id,
    )
    await db.commit()
    return {"customer_id": customer_id, "status": "stopped", "closure_summary": summary}
