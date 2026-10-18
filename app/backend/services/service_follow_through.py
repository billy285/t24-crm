"""Delivery follow-through and scoped Stripe signals; never financial mutations.

All renewal observations require a previously linked Checkout subscription. Raw
payloads, unrelated accounts/subscriptions, and payer data are never persisted.
"""
import hashlib
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select

from models.employees import Employees
from models.sales_deal_handoffs import SalesDealHandoff
from models.sales_deal_payments import SalesPaymentRequest, SalesStripeEvent, SalesStripeObservation
from models.service_follow_through import ServiceKickoff, ServiceKickoffAudit, ServiceRenewalEvent, ServiceRenewalSignal
from models.subscriptions import Subscriptions
from services.customer_permissions import get_customer_permissions, is_customer_owner
from services.sales_deal_handoffs import OPS_ROLES
from services.sales_workflow_locks import lock_sales_workflow

RENEWAL_EVENT_TYPES = {
    "invoice.paid", "invoice.payment_failed", "invoice.payment_action_required",
    "customer.subscription.updated", "customer.subscription.deleted",
}
ATTENTION = {"payment_failed", "action_required", "cancelled", "cancel_scheduled", "overdue"}
LABELS = {"payment_failed": "续费扣款失败", "action_required": "付款需要客户验证", "cancelled": "订阅已取消，需确认后续服务",
    "cancel_scheduled": "订阅已设定到期取消", "payment_observed": "账单付款已观察，仍由老板核对", "upcoming": "7 天内到期，需核对续费",
    "overdue": "登记日期已到，续费结果待核对", "unconnected": "未关联实时续费通知", "watching": "暂无已收到的异常，不代表全部正常"}
COVERAGE_NOTE = "仅接收本次新成交已关联 Stripe 订阅的后续通知，未回补历史；未收到通知不代表扣款正常。账单付款成功仍需老板核对，不自动记账、不停服、不修改订阅或权限。"


def today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def day(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except (ValueError, TypeError):
        return None


def instant_day(value):
    from services.sales_deal_payments import _instant
    point = _instant(value)
    return point.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() if point else None


async def live_actor(db, user, owner_only=False):
    actor = await db.get(Employees, int(user.id), populate_existing=True)
    if not actor or actor.status not in {"active", "probation"} or actor.role != user.role:
        raise HTTPException(403, "账号已停用或权限已变更，请重新登录")
    if owner_only and not is_customer_owner(user):
        raise HTTPException(403, "续费与经营异常仅老板可查看")
    return actor


async def observe_renewal(db, event, body):
    """Called only after sales callback signature/account/live/shape validation."""
    from services.sales_deal_payments import _id, _minor, _instant, _text
    kind, obj = event["type"], event["data"]["object"]
    invoice = kind.startswith("invoice.")
    if invoice:
        legacy_raw = obj.get("subscription")
        legacy = _id(legacy_raw, "sub_")
        parent = obj.get("parent") if isinstance(obj.get("parent"), dict) else {}
        details = parent.get("subscription_details") if isinstance(parent.get("subscription_details"), dict) else {}
        modern_raw = details.get("subscription")
        modern = _id(modern_raw, "sub_")
        if (legacy_raw is not None and not legacy) or (modern_raw is not None and not modern):
            return {"received": True}
        # Ambiguous or malformed relationships never widen the allowed scope.
        if legacy and modern and legacy != modern:
            return {"received": True}
        sub_id = legacy or modern
        resource = _id(obj.get("id"), "in_")
        status = {"invoice.paid": "payment_observed", "invoice.payment_failed": "payment_failed",
            "invoice.payment_action_required": "action_required"}[kind]
        if (kind == "invoice.paid" and obj.get("paid") is not True and obj.get("status") != "paid") or (
                kind != "invoice.paid" and (obj.get("paid") is True or obj.get("status") == "paid")):
            return {"received": True}
        amount = _minor(obj.get("amount_paid" if status == "payment_observed" else "amount_due"))
        currency = _text(obj.get("currency"), 3)
        currency = currency.upper() if currency and len(currency) == 3 and currency.isalpha() else None
        due_date = instant_day(obj.get("due_date"))
        period_end = instant_day(obj.get("period_end"))
    else:
        sub_id = resource = _id(obj.get("id"), "sub_")
        state = obj.get("status")
        if state not in {"active", "trialing", "past_due", "unpaid", "incomplete", "incomplete_expired", "paused", "canceled"}:
            return {"received": True}
        status = "cancelled" if kind.endswith("deleted") or state == "canceled" else (
            "cancel_scheduled" if obj.get("cancel_at_period_end") is True or obj.get("cancel_at") else (
            "payment_failed" if state in {"past_due", "unpaid", "incomplete_expired"} else (
            "action_required" if state in {"incomplete", "paused"} else "watching")))
        amount = currency = due_date = None
        period_end = instant_day(obj.get("current_period_end") or obj.get("cancel_at"))
    if not sub_id or not resource:
        return {"received": True}
    await lock_sales_workflow(db)
    if await db.get(SalesStripeEvent, event["id"]):
        raise HTTPException(409, "回调编号已用于其他通知")
    previous = await db.get(ServiceRenewalEvent, event["id"])
    digest = hashlib.sha256(body).hexdigest()
    if previous:
        if previous.payload_digest != digest:
            raise HTTPException(409, "回调编号已存在")
        return {"received": True}
    matches = (await db.execute(select(SalesPaymentRequest.handoff_id).join(SalesStripeObservation,
        SalesStripeObservation.request_id == SalesPaymentRequest.id).where(
            SalesStripeObservation.subscription_id == sub_id,
            SalesStripeObservation.status.in_(["paid_observed", "processing"]),
            SalesStripeObservation.match_issues == []))).scalars().all()
    handoff_ids = set(matches)
    if len(handoff_ids) != 1:
        return {"received": True}
    handoff = await db.get(SalesDealHandoff, next(iter(handoff_ids)))
    if not handoff or (currency and currency != handoff.currency):
        return {"received": True}
    signal = await db.scalar(select(ServiceRenewalSignal).where(ServiceRenewalSignal.resource_key == resource))
    if signal and (signal.handoff_id != handoff.id or signal.subscription_id != sub_id):
        raise HTTPException(409, "回调关联记录冲突")
    at = _instant(event["created"])
    apply = True
    if signal:
        # Per-invoice paid is terminal. A different invoice never clears it or a
        # different invoice's failure. Deleted subscriptions cannot resurrect.
        terminal = signal.status == ("payment_observed" if invoice else "cancelled")
        apply = not terminal and at >= utc(signal.latest_event_at)
        if invoice and status == "payment_observed":
            apply = True
        if not invoice and status == "cancelled":
            apply = True
        if at == utc(signal.latest_event_at) and not invoice and signal.status == "cancel_scheduled" and status == "watching":
            apply = False
    else:
        signal = ServiceRenewalSignal(handoff_id=handoff.id, subscription_id=sub_id, resource_key=resource,
            resource_type="invoice" if invoice else "subscription", status=status, latest_event_id=event["id"], latest_event_at=at)
        db.add(signal)
    if apply:
        signal.status, signal.amount_minor, signal.currency = status, amount, currency
        signal.due_date, signal.period_end = due_date, period_end
        signal.latest_event_at, signal.latest_event_id = at, event["id"]
        signal.received_at = now()
    await db.flush()
    db.add(ServiceRenewalEvent(event_id=event["id"], signal_id=signal.id, event_type=kind,
        payload_digest=digest, stripe_created_at=at))
    await db.flush()
    return {"received": True}


async def kickoff_authority(db, handoff_id, user, write=False):
    actor = await live_actor(db, user)
    handoff = await db.get(SalesDealHandoff, handoff_id, populate_existing=True)
    if not handoff:
        raise HTTPException(404, "开工清单不存在或尚未授权")
    owner = is_customer_owner(user)
    rights = await get_customer_permissions(db, user, handoff.customer_id)
    if not owner and (actor.role not in OPS_ROLES or not rights["modules"]["delivery"]["read"]):
        raise HTTPException(404, "开工清单不存在或尚未授权")
    can_edit = owner or (actor.id == handoff.operations_owner_employee_id and
        handoff.operations_status == "accepted" and rights["modules"]["delivery"]["write"])
    if write and not can_edit:
        raise HTTPException(403, "仅老板或已接收且获交付编辑权限的指定运营可修改清单")
    reason = None if can_edit else ("仅指定运营可编辑" if actor.id != handoff.operations_owner_employee_id else
        "请先由指定运营本人确认接收" if handoff.operations_status != "accepted" else "当前为交付只读权限，请老板授权编辑")
    return handoff, can_edit, reason


def template(handoff, due):
    platforms = [x for x in handoff.source_snapshot.get("selected_platforms", []) if isinstance(x, str)]
    tasks = [("platform_verification", "核对套餐与已选服务平台")]
    tasks += [(f"platform_{i + 1}_authorization", f"确认 {name} 平台授权") for i, name in enumerate(platforms)]
    if not platforms:
        tasks.append(("account_authorization", "确认套餐所需账号授权"))
    tasks += [("customer_materials", "收齐客户素材与品牌资料"), ("first_delivery_plan", "确认首次交付内容与安排")]
    return [{"key": key, "title": title, "status": "pending", "due_date": due, "note": "", "evidence": "",
        "completed_on": None, "updated_by_name": None, "updated_at": None} for key, title in tasks]


def valid_due(handoff, value):
    start, end = (day(handoff.source_snapshot.get(name)) for name in ("service_start_date", "service_end_date"))
    if not start or not end or end <= start:
        raise HTTPException(409, "原成交服务区间不完整，请先核对；清单不会改写原区间")
    if value < start or value >= end:
        raise HTTPException(400, "清单计划日期需在原成交服务开始日及结束日前，不会修改原服务区间")


def kickoff_summary(handoff, kickoff, can_edit, reason):
    items = kickoff.items if kickoff else []
    completed = sum(item["status"] == "completed" for item in items)
    blocked = sum(item["status"] == "blocked" for item in items)
    overdue_days = max((max(0, (today() - day(item["due_date"])).days) for item in items if item["status"] != "completed"), default=0)
    overdue = overdue_days > 0
    status = "missing" if not kickoff else "completed" if completed == len(items) else "overdue" if overdue else "in_progress"
    return {"handoff_id": handoff.id, "customer_id": handoff.customer_id,
        "business_name": handoff.source_snapshot.get("business_name"), "package_name": handoff.plan_snapshot.get("name"),
        "selected_platforms": handoff.source_snapshot.get("selected_platforms", []),
        "operations_owner_name": handoff.operations_owner_name, "operations_status": handoff.operations_status,
        "service_start_date": handoff.source_snapshot.get("service_start_date"), "service_end_date": handoff.source_snapshot.get("service_end_date"),
        "initialized": bool(kickoff), "can_edit": bool(can_edit), "read_only_reason": reason, "status": status,
        "completed_count": completed, "blocked_count": blocked, "total_count": len(items) if kickoff else len(template(handoff, "")),
        "first_delivery_due_date": kickoff.first_delivery_due_date if kickoff else None,
        "revision": kickoff.revision if kickoff else 0, "overdue_days": overdue_days,
        "waiting_days": max(0, (now() - utc(handoff.created_at)).days) if handoff.created_at else 0, "href": f"/operations-workbench?view=kickoffs&handoff={handoff.id}"}


async def kickoff_detail(db, handoff_id, user):
    handoff, can_edit, reason = await kickoff_authority(db, handoff_id, user)
    kickoff = await db.get(ServiceKickoff, handoff_id, populate_existing=True)
    audits = (await db.scalars(select(ServiceKickoffAudit).where(ServiceKickoffAudit.handoff_id == handoff_id)
        .order_by(ServiceKickoffAudit.id.desc()).limit(100))).all() if kickoff else []
    summary = kickoff_summary(handoff, kickoff, can_edit, reason)
    return {"kickoff": {**summary, "items": kickoff.items if kickoff else [], "audit": [
        {"id": row.id, "item_key": row.item_key, "action": row.action, "actor_name": row.actor_name,
            "created_at": row.created_at, "before": row.before, "after": row.after} for row in audits]}}


async def initialize_kickoff(db, handoff_id, payload, user):
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    handoff, _, _ = await kickoff_authority(db, handoff_id, user, write=True)
    valid_due(handoff, payload.first_delivery_due_date)
    due = payload.first_delivery_due_date.isoformat()
    existing = await db.get(ServiceKickoff, handoff_id, populate_existing=True)
    if existing:
        if existing.first_delivery_due_date != due:
            raise HTTPException(409, "清单已经建立，请逐项调整计划，不能重新生成覆盖进度")
        return await kickoff_detail(db, handoff_id, user)
    items = template(handoff, due)
    kickoff = ServiceKickoff(handoff_id=handoff_id, first_delivery_due_date=due, revision=1, items=items,
        template_snapshot={"package_name": handoff.plan_snapshot.get("name"), "plan_code": handoff.plan_snapshot.get("plan_code"),
            "platforms": handoff.source_snapshot.get("selected_platforms", [])}, created_by_id=int(user.id))
    db.add(kickoff)
    await db.flush()
    db.add(ServiceKickoffAudit(handoff_id=handoff_id, action="initialized", actor_id=int(user.id), actor_name=user.name,
        after={"first_delivery_due_date": due, "items": items}))
    await db.flush()
    return await kickoff_detail(db, handoff_id, user)


async def update_kickoff_item(db, handoff_id, item_key, payload, user):
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    handoff, _, _ = await kickoff_authority(db, handoff_id, user, write=True)
    kickoff = await db.get(ServiceKickoff, handoff_id, populate_existing=True)
    if not kickoff:
        raise HTTPException(409, "请先建立开工清单")
    if kickoff.revision != payload.revision:
        raise HTTPException(409, "清单已被其他人更新，请刷新后核对，避免覆盖")
    valid_due(handoff, payload.due_date)
    if payload.status in {"blocked", "completed"} and len(payload.note.strip()) < 3:
        raise HTTPException(400, "完成或受阻时请填写至少三个字的依据说明")
    if payload.status == "completed":
        if not payload.completed_on or payload.completed_on > today() or payload.completed_on < date(1900, 1, 1):
            raise HTTPException(400, "请填写真实准备完成日期，不能晚于今天或早于 1900 年")
    elif payload.completed_on is not None:
        raise HTTPException(400, "只有已完成项目可填写完成日期")
    # Plain text only, no remote fetch, attachment upload or credential storage.
    if any(ord(c) < 32 and c not in "\n\t" for c in payload.note + payload.evidence):
        raise HTTPException(400, "说明内容含无效控制字符")
    entries = [dict(item) for item in kickoff.items]
    before = next((dict(item) for item in entries if item["key"] == item_key), None)
    if before is None:
        raise HTTPException(404, "清单项目不存在")
    after = {**before, "status": payload.status, "due_date": payload.due_date.isoformat(), "note": payload.note,
        "evidence": payload.evidence, "completed_on": payload.completed_on.isoformat() if payload.completed_on else None,
        "updated_by_name": user.name, "updated_at": now().isoformat()}
    kickoff.items = [after if item["key"] == item_key else item for item in entries]
    if item_key == "first_delivery_plan":
        kickoff.first_delivery_due_date = payload.due_date.isoformat()
    kickoff.revision += 1
    kickoff.updated_at = now()
    db.add(ServiceKickoffAudit(handoff_id=handoff_id, item_key=item_key, action="updated", actor_id=int(user.id),
        actor_name=user.name, before=before, after=after))
    await db.flush()
    return await kickoff_detail(db, handoff_id, user)


async def kickoffs(db, user, status="all"):
    actor = await live_actor(db, user)
    if not is_customer_owner(user) and actor.role not in OPS_ROLES:
        raise HTTPException(403, "开工清单仅老板和已获交付权限的运营可查看")
    rows = (await db.scalars(select(SalesDealHandoff).order_by(SalesDealHandoff.id.desc()))).all()
    persisted = {row.handoff_id: row for row in (await db.scalars(select(ServiceKickoff))).all()}
    items = []
    for handoff in rows:
        try:
            _, can_edit, reason = await kickoff_authority(db, handoff.id, user)
        except HTTPException as error:
            if error.status_code == 404:
                continue
            raise
        items.append(kickoff_summary(handoff, persisted.get(handoff.id), can_edit, reason))
    counts = {"all": len(items), **{state: sum(item["status"] == state for item in items)
        for state in ("missing", "in_progress", "overdue", "completed")}}
    counts["blocked"] = sum(bool(item["blocked_count"]) for item in items)
    filtered = items if status == "all" else [item for item in items if (bool(item["blocked_count"]) if status == "blocked" else item["status"] == status)]
    return {"items": filtered, "counts": counts, "total": len(filtered)}


def signal_data(signal):
    return {"kind": signal.resource_type, "status": signal.status, "label": LABELS[signal.status],
        "invoice_id": signal.resource_key if signal.resource_type == "invoice" else None,
        "subscription_id": signal.subscription_id, "event_at": signal.latest_event_at,
        "amount": signal.amount_minor / 100 if signal.amount_minor is not None else None,
        "currency": signal.currency, "due_date": signal.due_date, "period_end": signal.period_end}


def _subscription_priority_timestamp(value):
    """Match subscription-utils.ts date-priority ordering without host TZ drift."""
    if value is None:
        return 0
    if isinstance(value, datetime):
        return utc(value).timestamp()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), timezone.utc).timestamp()
    try:
        return utc(datetime.fromisoformat(str(value).replace("Z", "+00:00"))).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0


def _effective_legacy_subscriptions(subscriptions):
    """Read-only counterpart of Customers.decorateCustomerSubscriptions.

    Pending registrations stay separate. Select the latest row for every
    customer/package BEFORE filtering status, so an ended/stopped replacement
    cannot resurrect an older active month. Known handoffs are retained by the
    caller independently; this function does not mutate or reconcile any rows.
    """
    def priority(row):
        return (*(_subscription_priority_timestamp(getattr(row, field, None)) for field in
            ("end_date", "next_payment_date", "updated_at", "created_at")), int(row.id or 0))

    ordered = sorted((row for row in subscriptions if row.status != "pending"), key=priority, reverse=True)
    selected = {}
    for row in ordered:
        package_name = row.package_name or getattr(row, "product_name", None) or ""
        names = sorted(part.strip().lower() for part in re.split(r"[、,，]", str(package_name)) if part.strip())
        key = (str(row.customer_id) if row.customer_id is not None and row.customer_id != "" else "unknown_customer",
            "|".join(names) or "__empty_package__")
        if key not in selected:
            selected[key] = row
    return list(selected.values())


async def renewals(db, user, status="all"):
    await live_actor(db, user, owner_only=True)
    handoffs = (await db.scalars(select(SalesDealHandoff).order_by(SalesDealHandoff.id.desc()))).all()
    from services.stripe_history_reconciliation import historical_renewal_coverage
    history = await historical_renewal_coverage(db)
    subscriptions = (await db.scalars(select(Subscriptions))).all()
    crm = {row.id: row for row in subscriptions}
    linked = (await db.execute(select(SalesPaymentRequest.handoff_id, SalesStripeObservation.subscription_id)
        .join(SalesStripeObservation, SalesStripeObservation.request_id == SalesPaymentRequest.id)
        .where(SalesStripeObservation.subscription_id.is_not(None), SalesStripeObservation.match_issues == [],
            SalesStripeObservation.status.in_(["paid_observed", "processing"])))).all()
    subscription_handoffs = {}
    for handoff_id, sub_id in linked:
        subscription_handoffs.setdefault(sub_id, set()).add(handoff_id)
    # Use the callback's same single-handoff relationship predicate. A reused
    # subscription across two sales is unknown coverage, never two healthy links.
    unambiguous_subscriptions = {sub_id for sub_id, ids in subscription_handoffs.items() if len(ids) == 1}
    linkmap = {}
    for handoff_id, sub_id in linked:
        if sub_id in unambiguous_subscriptions:
            linkmap.setdefault(handoff_id, set()).add(sub_id)
    signals = (await db.scalars(select(ServiceRenewalSignal).order_by(ServiceRenewalSignal.latest_event_at.desc()))).all()
    signalmap = {}
    for signal in signals:
        signalmap.setdefault(signal.handoff_id, []).append(signal)
    items = []
    used = set()
    sources = [(f"handoff-{row.id}", row, crm.get(row.subscription_id)) for row in handoffs]
    used.update(row.subscription_id for row in handoffs if row.subscription_id)
    sources += [(f"crm-{row.id}", None, row) for row in _effective_legacy_subscriptions(subscriptions)
        if row.id not in used and row.status in {"active", "trialing", "past_due", "expiring_soon", "renewal_pending", "expired"}]
    for identifier, handoff, sub in sources:
        observed = list(signalmap.get(handoff.id, [])) if handoff else []
        historical = history["by_crm_subscription"].get(sub.id) if sub else None
        if historical:
            observed.extend(historical["observations"])
        connected = bool(historical or (handoff and linkmap.get(handoff.id)))
        due = day(sub.next_payment_date) if sub else None
        # Stripe period_end is a billing observation, not a service-date rewrite.
        periods = [day(row.period_end) for row in observed if row.resource_type == "subscription" and row.period_end]
        if historical and historical["period_end"]:
            periods.append(day(historical["period_end"]))
        if periods:
            due = max(periods)
        if not due:
            due = day(handoff.source_snapshot.get("service_end_date")) if handoff else day(sub.end_date)
        days = (due - today()).days if due else None
        statuses = {row.status for row in observed}
        state = next((name for name in ("cancelled", "payment_failed", "action_required", "cancel_scheduled") if name in statuses), None)
        state_from_signal = bool(state)
        if not state and sub and sub.status == "past_due":
            state = "payment_failed"
        if not state and sub and sub.status in {"renewal_pending", "expired"}:
            state = "overdue"
        if not state and sub and sub.status == "expiring_soon":
            state = "upcoming"
        if not state:
            state = "overdue" if days is not None and days < 0 else "upcoming" if days is not None and days <= 7 else (
                "payment_observed" if "payment_observed" in statuses else "watching" if connected else "unconnected")
        # No observation means unknown. An unconnected row may still have an
        # upcoming/overdue date but must retain the explicit unconnected flag.
        items.append({"id": identifier, "handoff_id": handoff.id if handoff else None,
            "customer_id": handoff.customer_id if handoff else sub.customer_id,
            "business_name": handoff.source_snapshot.get("business_name") if handoff else sub.customer_name,
            "package_name": handoff.plan_snapshot.get("name") if handoff else sub.package_name,
            "billing_cycle": handoff.plan_snapshot.get("default_billing_cycle") if handoff else sub.billing_cycle,
            "due_date": due.isoformat() if due else None, "days_until_due": days,
            "connection_status": "linked" if connected else "unconnected", "status": state,
            "status_label": ("CRM 登记逾期，实际扣款待核对" if sub and sub.status == "past_due" else
                "CRM 登记续费待核对，请检查日期与付款" if sub and sub.status in {"renewal_pending", "expired"} else
                "CRM 登记即将到期，请检查日期与续费" if sub and sub.status == "expiring_soon" else LABELS[state]) if not state_from_signal else LABELS[state],
            "latest_event_at": max((utc(row.latest_event_at) for row in observed), default=None),
            "signals": [signal_data(row) for row in observed],
            "href": historical["href"] if historical else f"/sales-leads?view=handoffs&handoff={handoff.id}" if handoff else f"/customers?detail={sub.customer_id}&tab=renewals"})
    counts = {"all": len(items), "attention": sum(item["status"] in ATTENTION for item in items),
        "unconnected": sum(item["connection_status"] == "unconnected" for item in items),
        "upcoming": sum(item["status"] == "upcoming" for item in items)}
    coverage = {"scope": "新成交关联订阅 + CRM 登记日期观察", "note": COVERAGE_NOTE,
        "linked_subscriptions": len(unambiguous_subscriptions | history["subscription_ids"]), "unconnected_subscriptions": counts["unconnected"],
        "received_event_count": (await db.scalar(select(func.count()).select_from(ServiceRenewalEvent))) + history["received_event_count"],
        "latest_event_at": max([utc(row.latest_event_at) for row in signals] + ([history["latest_event_at"]] if history["latest_event_at"] else []), default=None)}
    from services.sales_deal_payments import webhook_secret
    coverage["webhook_configured"] = bool(webhook_secret())
    filtered = items if status == "all" else [item for item in items if (
        item["status"] in ATTENTION if status == "attention" else item["connection_status"] == "unconnected" if status == "unconnected" else item["status"] == "upcoming")]
    filtered.sort(key=lambda item: (0 if item["status"] in ATTENTION else 1, item["days_until_due"] if item["days_until_due"] is not None else 999999, item["id"]))
    return {"items": filtered, "counts": counts, "coverage": coverage, "total": len(filtered)}


async def owner_overview(db, user):
    await live_actor(db, user, owner_only=True)
    from services.sales_deal_handoffs import queue
    handoffs, kickoff_rows, renewal_rows = await queue(db, user), await kickoffs(db, user), await renewals(db, user)
    items = []
    kinds = {"pending_payment": ("pending_receipt", "成交收款待老板核对", "warning"),
        "pending_access": ("pending_access", "客户交付权限待老板邀请", "warning"),
        "pending_operations": ("pending_operations", "指定运营尚未确认接收", "info")}
    for row in handoffs["items"]:
        for field, (kind, title, severity) in kinds.items():
            if row[field]:
                items.append({"id": f"{kind}-{row['id']}", "kind": kind, "title": title,
                    "business_name": row.get("business_name"), "customer_id": row["customer_id"], "handoff_id": row["id"],
                    "waiting_days": row["waiting_days"], "severity": severity,
                    "href": f"/sales-leads?view=handoffs&handoff={row['id']}"})
    for row in kickoff_rows["items"]:
        if row["status"] in {"missing", "overdue"}:
            kind = "kickoff_" + row["status"]
            items.append({"id": f"{kind}-{row['handoff_id']}", "kind": kind,
                "title": "开工清单尚未建立" if row["status"] == "missing" else "开工项目已逾计划日期",
                "business_name": row["business_name"], "customer_id": row["customer_id"], "handoff_id": row["handoff_id"],
                "waiting_days": row["overdue_days"] if row["status"] == "overdue" else row["waiting_days"],
                "severity": "warning", "href": row["href"]})
    for row in kickoff_rows["items"]:
        if row["blocked_count"]:
            items.append({"id": f"kickoff_blocked-{row['handoff_id']}", "kind": "kickoff_blocked",
                "title": "开工准备受阻，需处理资料或授权", "business_name": row["business_name"],
                "customer_id": row["customer_id"], "handoff_id": row["handoff_id"], "waiting_days": row["overdue_days"],
                "severity": "warning", "href": row["href"]})
    for row in renewal_rows["items"]:
        if row["status"] in ATTENTION:
            unresolved_dates = [utc(signal["event_at"]) for signal in row["signals"] if signal["status"] in ATTENTION]
            waiting_days = max(0, (now() - min(unresolved_dates)).days) if unresolved_dates else max(0, -(row["days_until_due"] or 0))
            items.append({"id": f"renewal-{row['id']}", "kind": "renewal_attention", "title": row["status_label"],
                "business_name": row["business_name"], "customer_id": row["customer_id"], "handoff_id": row["handoff_id"],
                "waiting_days": waiting_days, "severity": "warning",
                "href": row["href"],
                "priority": 0 if any(signal["status"] in {"payment_failed", "action_required", "cancelled"} for signal in row["signals"]) else
                    15 if any(signal["status"] == "cancel_scheduled" for signal in row["signals"]) else 60})
    counts = {kind: sum(item["kind"] == kind for item in items) for kind in
        ("pending_receipt", "pending_access", "pending_operations", "kickoff_missing", "kickoff_overdue", "kickoff_blocked", "renewal_attention")}
    counts.update(renewal_unconnected=renewal_rows["counts"]["unconnected"], total_actions=len(items))
    priorities = {"pending_receipt": 10, "kickoff_blocked": 20, "kickoff_overdue": 21, "pending_access": 30,
        "pending_operations": 40, "kickoff_missing": 45}
    for item in items:
        item.setdefault("priority", priorities.get(item["kind"], 60))
    items.sort(key=lambda item: (item["priority"], -item["waiting_days"], item["id"]))
    return {"counts": counts, "items": items, "coverage": renewal_rows["coverage"], "generated_at": now(),
        "note": "按待办项计数，同一客户可能有多项；收款、客户授权与运营本人接收分别处理。"}
