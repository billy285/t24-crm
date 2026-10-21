"""Explicit historical bindings and original financial receipt checks.

Provider data is minimal and scoped by owner-approved identities. Historical
receipts require owner confirmation; separately authorized new invoices share
the same cash, duplicate, close and original financial checks.
"""
import asyncio
import hashlib
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from models.customers import Customers
from models.deals import Deals
from models.employees import Employees
from models.management_decisions import CustomerEngagement, ProductCatalog, ProductPlan
from models.payments import Payments
from models.sales_deal_payments import SalesStripeObservation
from models.stripe_history_reconciliation import (StripeHistoryAudit, StripeHistoryBinding, StripeHistoryEvent,
    StripeHistoryInvoiceReview, StripeHistoryPolicy, StripeHistoryPosting, StripeHistoryPreview)
from models.subscriptions import Subscriptions
from services import stripe_history_provider as provider
from services.customer_permissions import is_customer_owner
from services.finance_period_lock import ensure_payment_writes_open
from services.sales_deal_payments import _id, _instant, _minor
from services.sales_payment_catalog import STRIPE_ACCOUNT_ID
from services.sales_workflow_locks import lock_sales_workflow
from services.service_follow_through import _effective_legacy_subscriptions, day, live_actor, today, utc

PILOT_LIMIT = 5
ACTIVE_CRM = {"active", "trialing", "past_due", "expiring_soon", "renewal_pending", "expired"}
REVIEW_STATES = ("pending_review", "needs_refresh", "exception", "confirmed", "linked_existing")
NOTE = "历史付款保留老板核对；已单独授权服务的正常新账单可自动入账。原财务服务费、手续费、关账和分润规则不变。"
ISSUES = {
    "subscription_identity": "订阅关联编号不完整或冲突", "customer_identity": "付款客户与绑定客户不一致", "currency_mismatch": "币种与绑定不一致",
    "not_paid": "账单尚未付清", "out_of_band": "账单含外部手工标记付款，无法证明实际扣款", "non_cash_credit": "账单含余额、抵扣或贷项，需单独核对",
    "partial_payment": "账单非单笔全额付款", "multiple_items": "包含多个服务或不完整明细，不能猜测拆分", "proration": "包含升级补差或按比例调整",
    "discount": "包含折扣或优惠，需单独核对", "price_changed": "价格或服务周期与绑定快照不一致", "tax_incomplete": "税额与服务费拆分不完整或不平",
    "period_incomplete": "实际服务覆盖区间不完整或不合理", "payment_date": "缺少有效实际付款日期", "cash_unverified": "缺少一致的成功支付及已捕获扣款凭据",
    "refund_or_dispute": "付款存在退款或争议，需走原调整流程", "fee_unverified": "缺少一致的实际手续费与净额凭据", "scope_changed": "CRM 服务或业务归属已变化，需重新核对",
    "before_cutoff": "账单早于绑定的历史扫描起点", "provider_verification_required": "待通过专用只读接口更新实际付款凭据",
}


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


def minor(value):
    try:
        amount = Decimal(str(value)) * 100
        return int(amount) if amount.is_finite() and amount == int(amount) else None
    except (ValueError, TypeError, ArithmeticError):
        return None


def text(value, length=255):
    return value.strip()[:length] if isinstance(value, str) else ""


def package_key(value):
    return "|".join(sorted(part.strip().lower() for part in re.split(r"[、,，]", value or "") if part.strip()))


def issues_data(codes):
    return [{"code": code, "message": ISSUES.get(code, "凭据需核对")} for code in dict.fromkeys(codes)]


def audit(db, user, action, details, binding_id=None, review_id=None):
    db.add(StripeHistoryAudit(actor_id=int(user.id), actor_name=user.name, action=action,
        details=details, binding_id=binding_id, review_id=review_id))


async def owner(db, user):
    await live_actor(db, user, owner_only=True)


async def crm_snapshot(db, subscription_id, *, effective=True):
    subscription = await db.get(Subscriptions, subscription_id, populate_existing=True)
    customer = await db.get(Customers, subscription.customer_id, populate_existing=True) if subscription else None
    if not subscription or not customer:
        raise HTTPException(404, "CRM 客户或服务不存在")
    if subscription.status not in ACTIVE_CRM:
        raise HTTPException(409, "仅可绑定当前尚需管理续费的 CRM 服务，待开始或已停止服务不能绑定")
    if effective:
        current = _effective_legacy_subscriptions((await db.scalars(select(Subscriptions).where(Subscriptions.customer_id == customer.id))).all())
        if subscription.id not in {row.id for row in current}:
            raise HTTPException(409, "这是历史月份记录，请选择客户中心当前有效服务")
    engagement = await db.get(CustomerEngagement, subscription.engagement_id) if subscription.engagement_id else None
    product = await db.get(ProductCatalog, subscription.product_id) if subscription.product_id else None
    plan = await db.get(ProductPlan, subscription.product_plan_id) if subscription.product_plan_id else None
    deal = await db.get(Deals, subscription.deal_id) if subscription.deal_id else None
    if (engagement and engagement.customer_id != customer.id) or (subscription.engagement_id and not engagement) or (
            product and subscription.business_line_id and product.business_line_id != subscription.business_line_id) or (
            plan and subscription.product_id and plan.product_id != subscription.product_id) or (deal and deal.customer_id != customer.id):
        raise HTTPException(409, "服务的客户、项目或产品关联不一致，请先走原资料核对流程")
    return {"customer_id": customer.id, "customer_name": customer.business_name, "crm_subscription_id": subscription.id,
        "package_name": subscription.package_name, "amount": subscription.package_price,
        "currency": plan.default_currency if plan else product.default_currency if product else None,
        "billing_cycle": subscription.billing_cycle, "engagement_id": subscription.engagement_id,
        "business_line_id": subscription.business_line_id, "product_id": subscription.product_id,
        "product_plan_id": subscription.product_plan_id, "deal_id": subscription.deal_id}


async def crm_services(db, user, search=""):
    await owner(db, user)
    rows = _effective_legacy_subscriptions((await db.scalars(select(Subscriptions))).all())
    items = []
    for row in rows:
        if row.status not in ACTIVE_CRM:
            continue
        try:
            value = await crm_snapshot(db, row.id, effective=False)
        except HTTPException:
            continue
        if not search or search.casefold() in (value["customer_name"] + " " + value["package_name"] + " " + str(value["customer_id"])).casefold():
            items.append({**value, "status": row.status})
    return {"items": items[:200], "total": len(items), "truncated": len(items) > 200}


def subscription_data(raw):
    if raw.get("livemode") is not True or not _id(raw.get("id"), "sub_"):
        raise HTTPException(409, "订阅不是有效的正式账户记录")
    customer = raw.get("customer")
    customer_id = _id(customer, "cus_")
    container = raw.get("items") if isinstance(raw.get("items"), dict) else {}
    items = container.get("data") if isinstance(container.get("data"), list) else []
    first = items[0] if len(items) == 1 and isinstance(items[0], dict) else {}
    price = first.get("price") if isinstance(first.get("price"), dict) else {}
    recurring = price.get("recurring") if isinstance(price.get("recurring"), dict) else {}
    interval, count = recurring.get("interval"), recurring.get("interval_count")
    cycle = {( "month", 1): "monthly", ("month", 3): "quarterly", ("month", 6): "semi_annual", ("year", 1): "annual"}.get((interval, count))
    currency = text(price.get("currency"), 3).upper()
    amount = _minor(price.get("unit_amount"))
    return {"subscription_id": raw["id"], "customer_id": customer_id, "customer_name": text(customer.get("name")) if isinstance(customer, dict) else "",
        "email": text(customer.get("email"), 320) if isinstance(customer, dict) else "", "status": text(raw.get("status"), 32),
        "currency": currency, "amount": amount / 100 if amount is not None else None, "amount_minor": amount,
        "billing_cycle": cycle, "price_id": _id(price.get("id"), "price_"), "tax_behavior": text(price.get("tax_behavior"), 16),
        "period_start": _instant(raw.get("current_period_start")).isoformat() if _instant(raw.get("current_period_start")) else None,
        "period_end": _instant(raw.get("current_period_end")).isoformat() if _instant(raw.get("current_period_end")) else None,
        "items_count": len(items), "quantity": first.get("quantity"), "complete_items": container.get("has_more") is False,
        "valid": bool(customer_id and len(items) == 1 and container.get("has_more") is False and first.get("quantity") == 1
            and cycle and amount is not None and re.fullmatch("[A-Z]{3}", currency) and _id(price.get("id"), "price_"))}


async def stripe_subscriptions(db, user, customer_id=None, starting_after=None):
    await owner(db, user)
    rows, more = await provider.reader().subscriptions(customer_id, starting_after)
    values = [subscription_data(row) for row in rows]
    return {"items": values, "has_more": more, "next_cursor": values[-1]["subscription_id"] if more and values else None, "read_only": True}


async def pilot(db):
    bindings = (await db.scalars(select(StripeHistoryBinding).where(StripeHistoryBinding.status == "active"))).all()
    policy = await db.get(StripeHistoryPolicy, 1)
    validated = sum(row.pilot_validated and pilot_proof_current(row) for row in bindings)
    return {"limit": PILOT_LIMIT, "enabled_bindings": len(bindings), "validated_bindings": validated,
        "bulk_enabled": bool(policy and policy.bulk_enabled), "can_activate_bulk": validated >= 3}


def pilot_proof_current(row):
    proof = row.pilot_evidence or {}
    return bool(not row.needs_refresh and proof.get("successful_sync_count", 0) >= 2
        and proof.get("repeat_dedupe_verified") and proof.get("cash_evidence_verified")
        and proof.get("complete_page") and proof.get("invoice_count", 0) >= 1)


def invalidate_pilot(row):
    row.pilot_validated = False
    row.pilot_evidence = {**(row.pilot_evidence or {}), "repeat_dedupe_verified": False,
        "cash_evidence_verified": False, "last_digest": None}


def binding_data(row):
    evidence = row.pilot_evidence or {}
    return {"id": row.id, "customer_id": row.customer_id, "customer_name": row.crm_snapshot["customer_name"],
        "crm_subscription_id": row.crm_subscription_id, "package_name": row.crm_snapshot["package_name"],
        "stripe_subscription_id": row.stripe_subscription_id, "stripe_customer_id": row.stripe_customer_id,
        "currency": row.price_snapshot["currency"], "amount": row.price_snapshot["amount"],
        "billing_cycle": row.price_snapshot["billing_cycle"], "price_id": row.price_snapshot["price_id"],
        "sync_from": row.sync_from, "status": row.status, "revision": row.revision, "needs_refresh": row.needs_refresh,
        "last_synced_at": row.last_synced_at, "verified_at": row.created_at, "pilot_evidence": evidence,
        "pilot_validated": row.pilot_validated and pilot_proof_current(row),
        "validation_reason": None if pilot_proof_current(row) else "需完成待刷新凭据、相同范围同步两次并核验至少一笔完整付款凭据"}


async def preview_binding(db, payload, user):
    await owner(db, user)
    if payload.sync_from > today() or payload.sync_from < date(2020, 1, 1):
        raise HTTPException(400, "请选择 2020 年至今天之间的明确历史扫描起点")
    crm = await crm_snapshot(db, payload.crm_subscription_id)
    remote = subscription_data(await provider.reader().subscription(payload.stripe_subscription_id))
    if not remote["valid"]:
        raise HTTPException(409, "第一版仅支持单一、数量为一且周期明确的现有订阅，不会猜测多项目拆分")
    if await db.scalar(select(SalesStripeObservation.id).where(SalesStripeObservation.subscription_id == remote["subscription_id"]).limit(1)):
        raise HTTPException(409, "该订阅已由新成交付款流程管理，不能重复历史绑定")
    if await db.scalar(select(StripeHistoryBinding.id).where(or_(StripeHistoryBinding.stripe_subscription_id == remote["subscription_id"],
            StripeHistoryBinding.crm_subscription_id == crm["crm_subscription_id"])).limit(1)):
        raise HTTPException(409, "该 Stripe 订阅或 CRM 服务已有绑定，请查看原绑定，不能重复映射")
    warnings = []
    if crm["currency"] and crm["currency"] != remote["currency"]:
        raise HTTPException(409, "CRM 与 Stripe 币种不一致，不能建立自动核账绑定")
    for condition, code, message in (
        (not crm["currency"], "crm_currency_missing", "CRM 未登记币种，本次按现有 Stripe 币种核对，请确认"),
        (minor(crm["amount"]) != remote["amount_minor"], "price_differs_from_crm", "现有 Stripe 价格与 CRM 登记不同；保留原价，请确认是同一服务"),
        (crm["billing_cycle"] != remote["billing_cycle"], "cycle_differs_from_crm", "现有 Stripe 周期与 CRM 登记不同，请确认服务对应关系"),
        (remote["status"] not in {"active", "past_due"}, "subscription_status", "Stripe 订阅当前不是正常在服状态，请核对"),
    ):
        if condition:
            warnings.append({"code": code, "message": message})
    state = await pilot(db)
    can_confirm = state["bulk_enabled"] or state["enabled_bindings"] < PILOT_LIMIT
    token, expires = secrets.token_urlsafe(32), now() + timedelta(minutes=15)
    db.add(StripeHistoryPreview(token=token, actor_id=int(user.id), expires_at=expires,
        snapshot={"crm_service": crm, "stripe_subscription": remote, "warnings": warnings,
            "sync_from": payload.sync_from.isoformat(), "income_type": payload.income_type}))
    await db.flush()
    return {"token": token, "expires_at": expires, "crm_service": crm, "stripe_subscription": remote,
        "warnings": warnings, "can_confirm": can_confirm, "pilot": state, "note": NOTE}


async def confirm_binding(db, payload, user):
    await owner(db, user)
    preview = await db.get(StripeHistoryPreview, payload.token)
    if not preview or preview.actor_id != int(user.id) or utc(preview.expires_at) < now():
        raise HTTPException(409, "绑定预览已失效，请重新预览；未建立绑定")
    selected = preview.snapshot
    remote = subscription_data(await provider.reader().subscription(selected["stripe_subscription"]["subscription_id"]))
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    preview = await db.get(StripeHistoryPreview, payload.token, populate_existing=True)
    if preview.binding_id:
        return {"binding": binding_data(await db.get(StripeHistoryBinding, preview.binding_id)), "idempotent_replay": True}
    current = await crm_snapshot(db, selected["crm_service"]["crm_subscription_id"])
    if digest(current) != digest(selected["crm_service"]) or digest(remote) != digest(selected["stripe_subscription"]):
        raise HTTPException(409, "服务或 Stripe 订阅已变化，请重新预览，不会改写旧价格")
    if {item["code"] for item in selected["warnings"]} != set(payload.accepted_warning_codes):
        raise HTTPException(400, "请逐项确认预览中的差异提示")
    state = await pilot(db)
    if not state["bulk_enabled"] and state["enabled_bindings"] >= PILOT_LIMIT:
        raise HTTPException(409, "当前为最多五个绑定的试点；需完成至少三个试点核验后由老板明确启用批量")
    if await db.scalar(select(SalesStripeObservation.id).where(SalesStripeObservation.subscription_id == remote["subscription_id"]).limit(1)):
        raise HTTPException(409, "该订阅已由新成交管理，不能重复历史绑定")
    row = StripeHistoryBinding(account_id=STRIPE_ACCOUNT_ID, livemode=True, stripe_subscription_id=remote["subscription_id"],
        stripe_customer_id=remote["customer_id"], crm_subscription_id=current["crm_subscription_id"], customer_id=current["customer_id"],
        crm_snapshot=current, price_snapshot=remote, income_type=selected["income_type"], sync_from=selected["sync_from"], status="active",
        revision=1, needs_refresh=True, pilot_evidence={}, pilot_validated=False, verified_by_id=int(user.id), verified_by_name=user.name)
    db.add(row)
    await db.flush()
    preview.binding_id = row.id
    audit(db, user, "binding_confirmed", {"preview_token_digest": digest(payload.token), "warning_codes": payload.accepted_warning_codes}, row.id)
    return {"binding": binding_data(row), "idempotent_replay": False}


async def get_binding(db, binding_id, user, active=False):
    await owner(db, user)
    row = await db.get(StripeHistoryBinding, binding_id, populate_existing=True)
    if not row or row.account_id != STRIPE_ACCOUNT_ID or row.livemode is not True:
        raise HTTPException(404, "历史订阅绑定不存在")
    if active and row.status != "active":
        raise HTTPException(409, "绑定已暂停，不会继续采集或确认入账")
    return row


async def update_binding(db, binding_id, payload, user):
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    row = await get_binding(db, binding_id, user)
    if row.revision != payload.revision:
        raise HTTPException(409, "绑定已更新，请刷新后操作")
    if row.status != payload.status:
        state = await pilot(db)
        if payload.status == "active" and not state["bulk_enabled"] and state["enabled_bindings"] >= PILOT_LIMIT:
            raise HTTPException(409, "试点最多同时启用五个绑定")
        row.status, row.revision = payload.status, row.revision + 1
        invalidate_pilot(row)
        if payload.status == "active":
            row.needs_refresh = True
        audit(db, user, "binding_status", {"status": payload.status}, row.id)
    return {"binding": binding_data(row)}


def invoice_subscription(raw):
    legacy = _id(raw.get("subscription"), "sub_")
    parent = raw.get("parent") if isinstance(raw.get("parent"), dict) else {}
    details = parent.get("subscription_details") if isinstance(parent.get("subscription_details"), dict) else {}
    modern = _id(details.get("subscription"), "sub_")
    return None if legacy and modern and legacy != modern else legacy or modern


def charge_identifier(value):
    # Stripe Charge IDs can use ch_ or py_; neither proves payment success.
    # Refund IDs (including pyr_) and unknown prefixes are never Charge IDs.
    return _id(value, "ch_") or _id(value, "py_")


def invoice_snapshot(raw, binding):
    """Persist selected evidence only; lack of any cash proof holds the draft."""
    codes = []
    invoice_id = _id(raw.get("id"), "in_")
    subscription_id = invoice_subscription(raw)
    if raw.get("livemode") is not True or not invoice_id or subscription_id != binding.stripe_subscription_id:
        raise HTTPException(409, "账单不属于本次正式订阅绑定，不会保存")
    customer_id = _id(raw.get("customer"), "cus_")
    if customer_id != binding.stripe_customer_id:
        codes.append("customer_identity")
    currency = text(raw.get("currency"), 3).upper()
    if currency != binding.price_snapshot["currency"]:
        codes.append("currency_mismatch")
    created = _instant(raw.get("created"))
    if not created or created.date() < day(binding.sync_from):
        codes.append("before_cutoff")
    gross = _minor(raw.get("total"))
    service = _minor(raw.get("total_excluding_tax"))
    tax = gross - service if gross is not None and service is not None and gross >= service else None
    taxes = raw.get("total_tax_amounts")
    declared_tax = _minor(raw.get("tax"))
    if isinstance(taxes, list):
        amounts = [_minor(item.get("amount")) if isinstance(item, dict) else None for item in taxes]
        if all(value is not None for value in amounts):
            declared_tax = sum(amounts)
    if gross is None or service is None or tax is None or declared_tax != tax:
        codes.append("tax_incomplete")
    if raw.get("status") != "paid" or raw.get("paid") is not True:
        codes.append("not_paid")
    if raw.get("paid_out_of_band") is not False:
        codes.append("out_of_band")
    if any(raw.get(name, 0) not in (0, None) for name in ("starting_balance", "ending_balance", "pre_payment_credit_notes_amount", "post_payment_credit_notes_amount")):
        codes.append("non_cash_credit")
    if gross is None or gross <= 0 or raw.get("amount_due") != gross or raw.get("amount_paid") != gross or raw.get("amount_remaining") != 0:
        codes.append("partial_payment")
    if raw.get("discount") or raw.get("discounts") or raw.get("total_discount_amounts"):
        codes.append("discount")
    lines_container = raw.get("lines") if isinstance(raw.get("lines"), dict) else {}
    lines = lines_container.get("data") if isinstance(lines_container.get("data"), list) else []
    if len(lines) != 1 or lines_container.get("has_more") is not False:
        codes.append("multiple_items")
    first = lines[0] if len(lines) == 1 and isinstance(lines[0], dict) else {}
    if first.get("proration") is not False or first.get("type") != "subscription":
        codes.append("proration")
    price = first.get("price") if isinstance(first.get("price"), dict) else {}
    expected = binding.price_snapshot
    expected_total = gross if expected.get("tax_behavior") == "inclusive" else service
    if (_id(price.get("id"), "price_") != expected["price_id"] or first.get("quantity") != 1
            or expected_total != expected["amount_minor"]):
        codes.append("price_changed")
    period = first.get("period") if isinstance(first.get("period"), dict) else {}
    start, end = _instant(period.get("start")), _instant(period.get("end"))
    if not start or not end or end <= start or (end - start).days > 370:
        codes.append("period_incomplete")
    else:
        from services.sales_deal_handoffs import period_end
        if period_end(start.date(), expected["billing_cycle"]) != end.date():
            codes.append("price_changed")
    transitions = raw.get("status_transitions") if isinstance(raw.get("status_transitions"), dict) else {}
    paid_at = _instant(transitions.get("paid_at"))
    if not paid_at or paid_at > now() + timedelta(minutes=5):
        codes.append("payment_date")
    intent = raw.get("payment_intent") if isinstance(raw.get("payment_intent"), dict) else {}
    charge = intent.get("latest_charge") if isinstance(intent.get("latest_charge"), dict) else {}
    intent_id, charge_id = _id(intent.get("id"), "pi_"), charge_identifier(charge.get("id"))
    if (not intent_id or intent.get("livemode") is not True or intent.get("status") != "succeeded" or intent.get("amount_received") != gross
            or text(intent.get("currency"), 3).upper() != currency or not charge_id or charge.get("object") != "charge" or charge.get("livemode") is not True
            or charge.get("paid") is not True or charge.get("captured") is not True or charge.get("amount") != gross
            or charge.get("amount_captured") != gross or text(charge.get("currency"), 3).upper() != currency
            or _id(charge.get("payment_intent"), "pi_") != intent_id or _id(charge.get("invoice"), "in_") != invoice_id
            or _id(charge.get("customer"), "cus_") != binding.stripe_customer_id):
        codes.append("cash_unverified")
    if charge.get("refunded") is not False or charge.get("amount_refunded") != 0 or charge.get("disputed") is not False:
        codes.append("refund_or_dispute")
    balance = charge.get("balance_transaction") if isinstance(charge.get("balance_transaction"), dict) else {}
    fee, net = _minor(balance.get("fee")), _minor(balance.get("net"))
    balance_id = _id(balance.get("id"), "txn_")
    source_id = charge_identifier(balance.get("source"))
    # Stripe uses `payment` for successful local-payment charges. It is also
    # used while asynchronous payments are pending, so this type alone is never
    # cash proof: the invoice, succeeded intent and captured charge checks above
    # still apply, as do the exact source, gross, currency, fee and net checks.
    if (not balance_id or not charge_id or not source_id or balance.get("type") not in {"charge", "payment"} or source_id != charge_id
            or balance.get("amount") != gross or text(balance.get("currency"), 3).upper() != currency
            or fee is None or net is None or gross is None or fee > gross or net != gross - fee):
        codes.append("fee_unverified")
    return {"stripe_invoice_id": invoice_id, "stripe_subscription_id": subscription_id, "stripe_customer_id": customer_id,
        "stripe_payment_intent_id": intent_id, "stripe_charge_id": charge_id, "balance_transaction_id": balance_id,
        "currency": currency, "service_minor": service, "tax_minor": tax, "gross_minor": gross, "fee_minor": fee, "net_minor": net,
        "invoice_created": created.isoformat() if created else None, "invoice_status": text(raw.get("status"), 24),
        "payment_date": paid_at.date().isoformat() if paid_at else None,
        "coverage_start": start.date().isoformat() if start else None, "coverage_end": end.date().isoformat() if end else None,
        "lines": [{"description": text(line.get("description"), 400), "amount": (_minor(line.get("amount")) or 0) / 100,
            "currency": text(line.get("currency"), 3).upper(),
            "period_start": _instant((line.get("period") or {}).get("start")).date().isoformat() if isinstance(line.get("period"), dict) and _instant(line["period"].get("start")) else None,
            "period_end": _instant((line.get("period") or {}).get("end")).date().isoformat() if isinstance(line.get("period"), dict) and _instant(line["period"].get("end")) else None}
            for line in lines[:10] if isinstance(line, dict)], "issues": list(dict.fromkeys(codes))}


async def binding_context_matches(db, binding):
    try:
        current = await crm_snapshot(db, binding.crm_subscription_id, effective=False)
        return digest(current) == digest(binding.crm_snapshot)
    except HTTPException:
        return False


async def save_invoice(db, binding, raw):
    snapshot = invoice_snapshot(raw, binding)
    if not await binding_context_matches(db, binding):
        snapshot["issues"].append("scope_changed")
    row = await db.scalar(select(StripeHistoryInvoiceReview).where(StripeHistoryInvoiceReview.account_id == STRIPE_ACCOUNT_ID,
        StripeHistoryInvoiceReview.livemode.is_(True), StripeHistoryInvoiceReview.stripe_invoice_id == snapshot["stripe_invoice_id"]))
    if row and row.binding_id != binding.id:
        raise HTTPException(409, "账单已属于其他绑定，未重复保存")
    fingerprint = digest(snapshot)
    if row is None or row.fingerprint != fingerprint:
        invalidate_pilot(binding)
    if row is None:
        row = StripeHistoryInvoiceReview(account_id=STRIPE_ACCOUNT_ID, livemode=True, binding_id=binding.id,
            stripe_invoice_id=snapshot["stripe_invoice_id"], status="exception" if snapshot["issues"] else "pending_review",
            snapshot=snapshot, fingerprint=fingerprint, revision=1, needs_refresh=False)
        db.add(row)
    elif row.fingerprint != fingerprint:
        row.snapshot, row.fingerprint, row.revision, row.observed_at = snapshot, fingerprint, row.revision + 1, now()
        if row.status not in {"confirmed", "linked_existing"}:
            row.status = "exception" if snapshot["issues"] else "pending_review"
    row.needs_refresh = False
    await db.flush()
    from services.stripe_auto_posting import enqueue_review
    await enqueue_review(db, row, binding)
    return row


async def sync_invoices(db, binding_id, payload, user):
    binding = await get_binding(db, binding_id, user, active=True)
    if payload.date_start < day(binding.sync_from) or payload.date_end <= payload.date_start or (payload.date_end - payload.date_start).days > 93 or payload.date_end > today() + timedelta(days=1):
        raise HTTPException(400, "扫描区间需在绑定起点之后，结束日不晚于明天且为不含结束日的最多 93 天")
    start = int(datetime.combine(payload.date_start, datetime.min.time(), timezone.utc).timestamp())
    end = int(datetime.combine(payload.date_end, datetime.min.time(), timezone.utc).timestamp())
    raw_rows, more = await provider.reader().invoices(binding.stripe_subscription_id, start, end, payload.starting_after)
    # A provider page must satisfy the requested subscription and date filters;
    # never trust an unrelated record merely because it appeared in a list.
    for raw in raw_rows:
        created = _instant(raw.get("created"))
        if not created or not start <= created.timestamp() < end:
            raise HTTPException(409, "Stripe 返回了扫描区间外账单，本次没有保存")
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    binding = await get_binding(db, binding_id, user, active=True)
    rows = [await save_invoice(db, binding, raw) for raw in raw_rows]
    proof = {"range": [payload.date_start.isoformat(), payload.date_end.isoformat()],
        "invoices": sorted((row.stripe_invoice_id, row.fingerprint) for row in rows)}
    prior = binding.pilot_evidence or {}
    same = not more and not payload.starting_after and prior.get("last_digest") == digest(proof)
    cash = any(not row.snapshot.get("issues") for row in rows)
    binding.pilot_evidence = {"successful_sync_count": prior.get("successful_sync_count", 0) + 1,
        "repeat_dedupe_verified": bool(same), "cash_evidence_verified": cash, "invoice_count": len(rows),
        "safe_invoice_count": sum(not row.snapshot.get("issues") for row in rows), "exception_invoice_count": sum(bool(row.snapshot.get("issues")) for row in rows),
        "last_digest": digest(proof), "last_date_start": payload.date_start.isoformat(), "last_date_end": payload.date_end.isoformat(),
        "complete_page": not more and not payload.starting_after}
    if binding.pilot_validated and (not cash or not same):
        binding.pilot_validated = False
    binding.last_synced_at, binding.needs_refresh, binding.revision = now(), more, binding.revision + 1
    audit(db, user, "invoices_synced", {"date_start": payload.date_start.isoformat(), "date_end": payload.date_end.isoformat(),
        "invoice_count": len(rows), "has_more": more, "repeat_dedupe_verified": same}, binding.id)
    return {"items": [review_summary(row, binding) for row in rows], "has_more": more,
        "next_cursor": rows[-1].stripe_invoice_id if more and rows else None,
        "scope": {"date_start": payload.date_start.isoformat(), "date_end": payload.date_end.isoformat(), "end_exclusive": True}, "binding": binding_data(binding)}


async def validate_pilot(db, binding_id, payload, user):
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    binding = await get_binding(db, binding_id, user, active=True)
    proof = binding.pilot_evidence or {}
    if binding.revision != payload.revision:
        raise HTTPException(409, "绑定已更新，请重新查看同步证明")
    if not pilot_proof_current(binding):
        raise HTTPException(409, "需同一区间至少两次同步，确认去重稳定、完整付款依据一致后才能通过试点；无需正式记账")
    binding.pilot_validated, binding.revision = True, binding.revision + 1
    audit(db, user, "pilot_validated", {"verification_note": payload.verification_note, "evidence": proof}, binding.id)
    return {"binding": binding_data(binding), "pilot": await pilot(db)}


async def activate_bulk(db, payload, user):
    await owner(db, user)
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    rows = [row for row in (await db.scalars(select(StripeHistoryBinding).where(StripeHistoryBinding.status == "active",
        StripeHistoryBinding.pilot_validated.is_(True)))).all() if pilot_proof_current(row)]
    if len(rows) < 3:
        raise HTTPException(409, "至少三个当前试点绑定需先完成明确核验；不会自动开放批量")
    policy = await db.get(StripeHistoryPolicy, 1)
    if not policy:
        db.add(StripeHistoryPolicy(id=1, bulk_enabled=True, validated_binding_ids=[row.id for row in rows], verified_by_id=int(user.id), verification_note=payload.verification_note))
        audit(db, user, "bulk_activated", {"validated_binding_ids": [row.id for row in rows], "verification_note": payload.verification_note})
    await db.flush()
    return {"pilot": await pilot(db), "auto_accounting": False}


async def observe_history_event(db, event, body):
    """The outer sales callback already verified signature, account and live mode.

    Lifecycle notifications schedule a scoped refresh; they are never cash proof
    or ledger authority, and unmapped account-wide payloads are discarded.
    """
    raw = event["data"]["object"]
    sub_id = invoice_subscription(raw) if event["type"].startswith("invoice.") else _id(raw.get("id"), "sub_")
    if not sub_id:
        return
    binding = await db.scalar(select(StripeHistoryBinding).where(StripeHistoryBinding.account_id == STRIPE_ACCOUNT_ID,
        StripeHistoryBinding.livemode.is_(True), StripeHistoryBinding.stripe_subscription_id == sub_id, StripeHistoryBinding.status == "active"))
    if not binding:
        return
    await lock_sales_workflow(db)
    previous = await db.get(StripeHistoryEvent, event["id"])
    payload_digest = hashlib.sha256(body).hexdigest()
    if previous:
        if previous.payload_digest != payload_digest:
            raise HTTPException(409, "Stripe 历史通知编号已存在")
        return
    binding = await db.get(StripeHistoryBinding, binding.id, populate_existing=True)
    if binding.status != "active":
        return
    if event["type"].startswith("invoice."):
        invoice_id, created = _id(raw.get("id"), "in_"), _instant(raw.get("created"))
        if not invoice_id or not created or created.date() < day(binding.sync_from):
            return
        row = await db.scalar(select(StripeHistoryInvoiceReview).where(StripeHistoryInvoiceReview.account_id == STRIPE_ACCOUNT_ID,
            StripeHistoryInvoiceReview.livemode.is_(True), StripeHistoryInvoiceReview.stripe_invoice_id == invoice_id))
        if row and row.binding_id != binding.id:
            raise HTTPException(409, "账单通知关联冲突")
        if not row:
            snapshot = {"stripe_invoice_id": invoice_id, "invoice_created": created.isoformat(), "issues": ["provider_verification_required"]}
            db.add(StripeHistoryInvoiceReview(account_id=STRIPE_ACCOUNT_ID, livemode=True, stripe_invoice_id=invoice_id,
                binding_id=binding.id, status="needs_refresh", snapshot=snapshot, fingerprint=digest(snapshot), revision=1, needs_refresh=True))
        else:
            row.needs_refresh = True
    if event["type"].startswith("invoice."):
        resource_key = _id(raw.get("id"), "in_")
        signal_status = {"invoice.paid": "payment_observed", "invoice.payment_failed": "payment_failed", "invoice.payment_action_required": "action_required"}[event["type"]]
        details = {}
    else:
        resource_key = sub_id
        signal_status = "cancelled" if event["type"].endswith("deleted") or raw.get("status") == "canceled" else (
            "cancel_scheduled" if raw.get("cancel_at_period_end") is True or raw.get("cancel_at") else (
            "payment_failed" if raw.get("status") in {"past_due", "unpaid", "incomplete_expired"} else (
            "action_required" if raw.get("status") in {"incomplete", "paused"} else "watching")))
        end = _instant(raw.get("current_period_end") or raw.get("cancel_at"))
        details = {"period_end": end.date().isoformat() if end else None}
    binding.needs_refresh = True
    invalidate_pilot(binding)
    binding.revision += 1
    db.add(StripeHistoryEvent(event_id=event["id"], binding_id=binding.id, event_type=event["type"], resource_key=resource_key,
        signal_status=signal_status, details=details, payload_digest=payload_digest, stripe_created_at=_instant(event["created"])))
    await db.flush()
    if event["type"].startswith("invoice."):
        queued = await db.scalar(select(StripeHistoryInvoiceReview).where(StripeHistoryInvoiceReview.stripe_invoice_id == resource_key, StripeHistoryInvoiceReview.binding_id == binding.id))
        if queued:
            from services.stripe_auto_posting import enqueue_review
            await enqueue_review(db, queued, binding)


def review_summary(row, binding):
    value = row.snapshot
    return {"id": row.id, "binding_id": binding.id, "customer_id": binding.customer_id,
        "customer_name": binding.crm_snapshot["customer_name"], "package_name": binding.crm_snapshot["package_name"],
        "stripe_invoice_id": row.stripe_invoice_id, "status": row.status, "revision": row.revision,
        "issues": issues_data(value.get("issues", [])), "currency": value.get("currency"),
        **{name + "_amount": value.get(name + "_minor") / 100 if value.get(name + "_minor") is not None else None for name in ("service", "tax", "gross", "fee", "net")},
        "payment_date": value.get("payment_date"), "coverage_start": value.get("coverage_start"), "coverage_end": value.get("coverage_end"),
        "observed_at": row.observed_at, "needs_refresh": row.needs_refresh}


def accounting_payload(binding, snapshot, user):
    from services.deal_payment_sync import _calculate_stripe_fee, _derive_income_split
    amount = snapshot["service_minor"] / 100
    fee = _calculate_stripe_fee(amount, "stripe", "subscription_auto")
    management, ads = _derive_income_split(binding.income_type, amount)
    moment = lambda value: datetime.combine(day(value), datetime.min.time(), timezone.utc)
    return {"customer_id": binding.customer_id, "customer_name": binding.crm_snapshot["customer_name"],
        "source_deal_id": None, "engagement_id": binding.crm_snapshot["engagement_id"],
        "business_line_id": binding.crm_snapshot["business_line_id"], "product_id": binding.crm_snapshot["product_id"],
        "income_type": binding.income_type, "product_name": binding.crm_snapshot["package_name"],
        "amount_due": amount, "amount_paid": amount, "management_amount": management, "ads_recharge_amount": ads,
        "stripe_fee_amount": fee, "net_amount": max(amount - fee, 0.0), "currency": snapshot["currency"],
        "payment_date": moment(snapshot["payment_date"]), "payment_mode": "subscription_auto", "payment_method": "stripe",
        "transaction_reference": snapshot["stripe_invoice_id"], "billing_cycle": binding.price_snapshot["billing_cycle"],
        "coverage_start": moment(snapshot["coverage_start"]), "coverage_end": moment(snapshot["coverage_end"]), "has_invoice": True,
        "outstanding_amount": 0.0, "expense_month": snapshot["payment_date"][:7], "recorded_by": user.name,
        "notes": "老板核对历史 Stripe 账单；税及实际手续费保存在独立核款依据，未改原财务公式", "created_at": now(), "user_id": str(user.id)}


def reference_matches(value, identities):
    parts = set(re.findall(r"(?:in_|pi_|ch_|py_)[A-Za-z0-9_]+", str(value or "")))
    return bool({part.casefold() for part in parts} & {part.casefold() for part in identities if part})


async def existing_candidates(db, binding, snapshot):
    identities = [snapshot.get(name) for name in ("stripe_invoice_id", "stripe_payment_intent_id", "stripe_charge_id")]
    result = []
    rows = (await db.scalars(select(Payments))).all()
    for payment in rows:
        exact_reference = reference_matches(payment.transaction_reference, identities)
        paid_date = day(payment.payment_date)
        target_date = day(snapshot.get("payment_date"))
        overlap = day(payment.coverage_start) == day(snapshot.get("coverage_start")) if payment.coverage_start else False
        near = bool(paid_date and target_date and abs((paid_date - target_date).days) <= 7)
        plausible = (payment.customer_id == binding.customer_id and minor(payment.amount_paid) in {snapshot.get("service_minor"), snapshot.get("gross_minor")}
            and (payment.currency or "USD").upper() == snapshot.get("currency") and (near or overlap))
        if exact_reference or plausible:
            result.append(payment)
    # Cross-reference the old initial receipt too; its invoice identity may be
    # in a separate evidence row rather than the free-form manual reference.
    from models.sales_deal_handoffs import SalesDealHandoff
    from models.sales_deal_payments import SalesReceiptEvidence
    identity_filters = [getattr(SalesStripeObservation, field) == snapshot[key] for field, key in
        (("invoice_id", "stripe_invoice_id"), ("payment_intent_id", "stripe_payment_intent_id")) if snapshot.get(key)]
    matched = (await db.execute(select(SalesDealHandoff.payment_id).join(SalesReceiptEvidence,
        SalesReceiptEvidence.handoff_id == SalesDealHandoff.id).join(SalesStripeObservation,
        SalesStripeObservation.id == SalesReceiptEvidence.observation_id).where(or_(*identity_filters)))).scalars().all() if identity_filters else []
    for payment_id in matched:
        payment = await db.get(Payments, payment_id) if payment_id else None
        if payment and payment.id not in {row.id for row in result}:
            result.append(payment)
    return result


def candidate_data(payment):
    return {field: getattr(payment, field) for field in ("id", "customer_name", "product_name", "amount_paid", "payment_date",
        "currency", "transaction_reference", "coverage_start", "coverage_end")}


async def get_review(db, review_id, user):
    await owner(db, user)
    row = await db.get(StripeHistoryInvoiceReview, review_id, populate_existing=True)
    if not row or row.account_id != STRIPE_ACCOUNT_ID or row.livemode is not True:
        raise HTTPException(404, "待核账单不存在")
    binding = await get_binding(db, row.binding_id, user)
    return row, binding


async def detail(db, review_id, user):
    row, binding = await get_review(db, review_id, user)
    value = row.snapshot
    summary = review_summary(row, binding)
    from services.stripe_auto_posting import review_evidence
    summary["auto_posting"] = await review_evidence(db, row.id)
    candidate_rows = await existing_candidates(db, binding, value) if value.get("service_minor") is not None else []
    posting = await db.get(StripeHistoryPosting, row.id)
    reason = None
    payload = None
    commission_preview = None
    if posting:
        reason = "该账单已完成确认，不会再次入账"
    elif binding.status != "active":
        reason = "绑定已暂停"
    elif value.get("issues") or row.status == "needs_refresh":
        reason = "付款依据存在异常或尚待更新，请先核对；不能正式入账"
    elif not await binding_context_matches(db, binding):
        reason = "CRM 业务关联已变化，请先核对"
    else:
        payload = accounting_payload(binding, value, user)
        try:
            await ensure_payment_writes_open(db, [payload], action="核对历史 Stripe 账单")
            from services.commissions import commission_ledger_available, preview_payment_commission
            if await commission_ledger_available(db):
                commission_preview = await preview_payment_commission(db, Payments(**payload))
                if commission_preview["issues"]:
                    reason = "现有分润归属或服务区间需核对；不会重新建立首月或猜测归属"
        except HTTPException as error:
            reason = str(error.detail)
    can_confirm = reason is None
    return {"review": {**summary, "lines": value.get("lines", []), "existing_payment_candidates": [candidate_data(item) for item in candidate_rows],
        "accounting_preview": payload, "commission_preview": commission_preview, "can_confirm": can_confirm,
        "can_create_payment": can_confirm and not candidate_rows, "can_link_existing": can_confirm and bool(candidate_rows),
        "read_only_reason": reason, "payment_id": posting.payment_id if posting else None, "note": NOTE}}


async def reviews(db, user, status="all"):
    await owner(db, user)
    rows = (await db.scalars(select(StripeHistoryInvoiceReview).order_by(StripeHistoryInvoiceReview.id.desc()))).all()
    bindings = {row.id: row for row in (await db.scalars(select(StripeHistoryBinding))).all()}
    counts = {"all": len(rows), **{state: sum(row.status == state for row in rows) for state in REVIEW_STATES}}
    selected = rows if status == "all" else [row for row in rows if row.status == status]
    from services.stripe_auto_posting import review_evidence
    items = []
    automatic = 0
    manual_pending = 0
    for row in rows:
        evidence = await review_evidence(db, row.id)
        if evidence and evidence["status"] == "auto_posted":
            automatic += 1
        if row.status in {"pending_review", "needs_refresh"} and not (evidence and evidence["status"] in {"queued", "retry"}):
            manual_pending += 1
        if row in selected:
            items.append({**review_summary(row, bindings[row.binding_id]), "auto_posting": evidence})
    counts["auto_posted"] = automatic
    counts["manual_confirmed"] = counts["confirmed"] - automatic
    counts["manual_pending"] = manual_pending
    return {"items": items, "counts": counts, "total": len(selected)}


async def refresh_review(db, review_id, user):
    row, binding = await get_review(db, review_id, user)
    if binding.status != "active":
        raise HTTPException(409, "绑定已暂停")
    raw = await provider.reader().invoice(row.stripe_invoice_id)
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    binding = await get_binding(db, binding.id, user, active=True)
    row = await save_invoice(db, binding, raw)
    audit(db, user, "invoice_refreshed", {"fingerprint": row.fingerprint}, binding.id, row.id)
    return await detail(db, row.id, user)


def validate_existing(payment, binding, value):
    if payment.customer_id != binding.customer_id or minor(payment.amount_paid) != value["service_minor"] or minor(payment.amount_due) != value["service_minor"]:
        raise HTTPException(409, "原收款的客户或服务费不一致，不能强行关联")
    if (payment.currency or "USD").upper() != value["currency"] or package_key(payment.product_name) != package_key(binding.crm_snapshot["package_name"]):
        raise HTTPException(409, "原收款币种或服务名称不一致，请从原财务流程核对")
    for field in ("engagement_id", "business_line_id", "product_id"):
        if getattr(payment, field) != binding.crm_snapshot[field]:
            raise HTTPException(409, "原收款项目或业务归属不同，不能猜测分配")
    for field in ("coverage_start", "coverage_end"):
        if getattr(payment, field) is not None and day(getattr(payment, field)) != day(value[field]):
            raise HTTPException(409, "原收款服务覆盖区间不同，不能重复关联")
    if not day(payment.payment_date) or abs((day(payment.payment_date) - day(value["payment_date"])).days) > 1:
        raise HTTPException(409, "原收款日期与实际付款日期不同，请先核对")
    if payment.source_deal_id and payment.source_deal_id != binding.crm_snapshot["deal_id"]:
        raise HTTPException(409, "原收款属于其他成交，不能重新归属")


async def confirm_invoice(db, review_id, payload, user):
    row, binding = await get_review(db, review_id, user)
    existing_post = await db.get(StripeHistoryPosting, row.id)
    if existing_post:
        if existing_post.action != payload.action or (payload.action == "link_existing" and existing_post.payment_id != payload.existing_payment_id):
            raise HTTPException(409, "该账单已经确认，不能覆盖原核对结果")
        return {**await detail(db, row.id, user), "payment_id": existing_post.payment_id, "idempotent_replay": True}
    raw = await provider.reader().invoice(row.stripe_invoice_id)
    fresh = invoice_snapshot(raw, binding)
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    row, binding = await get_review(db, review_id, user)
    existing_post = await db.get(StripeHistoryPosting, row.id)
    if existing_post:
        if existing_post.action != payload.action or (payload.action == "link_existing" and existing_post.payment_id != payload.existing_payment_id):
            raise HTTPException(409, "该账单已经确认，不能覆盖原核对结果")
        return {**await detail(db, row.id, user), "payment_id": existing_post.payment_id, "idempotent_replay": True}
    return await apply_verified_invoice(db, row, binding, fresh, revision=payload.revision, action=payload.action,
        existing_payment_id=payload.existing_payment_id, verification_note=payload.verification_note, user=user)


async def apply_verified_invoice(db, row, binding, fresh, *, revision, action, existing_payment_id, verification_note, user, source="owner"):
    """Shared original ledger transaction; caller holds workflow lock and authority.

    No provider notification alone reaches this function. Both callers require
    the same fresh cash evidence, collision, closing and original commission checks.
    """
    if binding.status != "active" or not await binding_context_matches(db, binding):
        raise HTTPException(409, "绑定或 CRM 服务关联已变化，未记账")
    if row.revision != revision or digest(fresh) != row.fingerprint:
        raise HTTPException(409, "付款依据已变化，请先刷新账单并重新核对，未记账")
    if fresh["issues"] or row.status != "pending_review":
        raise HTTPException(409, "尚无一致的实际扣款、税费及净额证明，不能入账")
    collision = await db.scalar(select(StripeHistoryPosting).where(StripeHistoryPosting.account_id == STRIPE_ACCOUNT_ID,
        StripeHistoryPosting.livemode.is_(True), StripeHistoryPosting.stripe_charge_id == fresh["stripe_charge_id"]))
    if collision:
        raise HTTPException(409, "同一实际扣款已用于其他账单，未重复入账")
    candidates = await existing_candidates(db, binding, fresh)
    ledger = accounting_payload(binding, fresh, user)
    if source == "system_auto":
        ledger["recorded_by"] = "系统自动入账（授权：" + user.name + "）"
        ledger["notes"] = "已授权订阅的新账单由系统核验实际扣款后自动入账；税及实际手续费独立留存，沿用原财务公式"
    await ensure_payment_writes_open(db, [ledger], action="确认历史 Stripe 收款")
    if action == "create_payment":
        if existing_payment_id is not None:
            raise HTTPException(400, "新增收款不能同时指定原记录")
        if candidates:
            raise HTTPException(409, "已有可能对应的手工或系统收款，请先选择原记录核对，未重复新增")
        payment = Payments(**ledger)
        db.add(payment)
        await db.flush()
        from services.commissions import commission_ledger_available, preview_payment_commission, sync_payment_commission
        if await commission_ledger_available(db):
            before_scope = (payment.engagement_id, payment.business_line_id, payment.product_id)
            preview = await preview_payment_commission(db, payment)
            if preview["issues"]:
                raise HTTPException(409, "原分润归属或覆盖区间不完整，未记账；不会新建归属或首月起点")
            try:
                await sync_payment_commission(db, payment)
            except ValueError as error:
                raise HTTPException(409, "原分润依据不完整，未记账，请先走原归属核对流程") from error
            if before_scope != (payment.engagement_id, payment.business_line_id, payment.product_id):
                raise HTTPException(409, "原分润流程识别的业务归属不同，未记账，请先核对")
        row.status = "confirmed"
    else:
        payment = await db.get(Payments, existing_payment_id, populate_existing=True) if existing_payment_id else None
        if not payment or payment.id not in {item.id for item in candidates}:
            raise HTTPException(409, "所选原收款不属于本次待核账候选，不能关联")
        validate_existing(payment, binding, fresh)
        await ensure_payment_writes_open(db, [payment], payment_ids=[payment.id], action="关联历史 Stripe 收款")
        if await db.scalar(select(StripeHistoryPosting.review_id).where(StripeHistoryPosting.payment_id == payment.id)):
            raise HTTPException(409, "原收款已经关联另一张账单，不能重复使用")
        row.status = "linked_existing"
    db.add(StripeHistoryPosting(review_id=row.id, account_id=STRIPE_ACCOUNT_ID, livemode=True, stripe_charge_id=fresh["stripe_charge_id"],
        payment_id=payment.id, action="auto_create_payment" if source == "system_auto" else action, fingerprint=row.fingerprint, verified_by_id=int(user.id), verified_by_name="系统自动（授权：" + user.name + "）" if source == "system_auto" else user.name,
        verification_note=verification_note))
    audit(db, user, "invoice_auto_posted" if source == "system_auto" else "invoice_confirmed", {"source": source, "authorized_by_id": int(user.id), "action": action, "payment_id": payment.id, "fingerprint": row.fingerprint,
        "verification_note": verification_note}, binding.id, row.id)
    if source == "owner":
        from models.stripe_auto_posting import StripeAutoPostingJob
        auto_job = await db.get(StripeAutoPostingJob, row.id)
        if auto_job:
            auto_job.status, auto_job.payment_id, auto_job.processed_at = "manual_completed", payment.id, now()
            auto_job.reason_code, auto_job.reason = "owner_processed", "已由老板人工核对处理"
            auto_job.retry_at = auto_job.lease_token = auto_job.lease_until = None
    row.revision += 1
    await db.flush()
    return {**await detail(db, row.id, user), "payment_id": payment.id, "idempotent_replay": False}


async def overview(db, user):
    await owner(db, user)
    bindings = (await db.scalars(select(StripeHistoryBinding).order_by(StripeHistoryBinding.id.desc()))).all()
    invoice_reviews = await reviews(db, user)
    configured = bool(provider.read_secret())
    from services.stripe_auto_posting import summary as automatic_summary
    automatic = await automatic_summary(db)
    return {"configured": configured, "provider_status": "configured" if configured else "not_configured", "auto_accounting": automatic["enabled_count"] > 0,
        "pilot": await pilot(db), "counts": {"bindings": len(bindings), **invoice_reviews["counts"]},
        "bindings": [binding_data(row) for row in bindings], "invoice_reviews": invoice_reviews["items"][:100], "scope_note": NOTE}


_BACKGROUND_LOCK = asyncio.Lock()


def background_sessions():
    from core.database import db_manager
    return db_manager.async_session_maker


async def process_pending_history():
    """Post-commit bounded recovery for persisted, already owner-bound drafts.

    Each invocation checks at most five invoice records. A provider failure keeps
    its queue flag, so a later signed event or owner refresh recovers it. This
    worker never calls the formal posting path or touches legacy financial rows.
    """
    sessions = background_sessions()
    if sessions is None or _BACKGROUND_LOCK.locked():
        return {"processed": 0, "deferred": True}
    processed = 0
    deadline = asyncio.get_running_loop().time() + 30
    async with _BACKGROUND_LOCK:
        try:
            async with sessions() as db:
                rows = (await db.scalars(select(StripeHistoryInvoiceReview).join(StripeHistoryBinding,
                    StripeHistoryBinding.id == StripeHistoryInvoiceReview.binding_id).where(
                        StripeHistoryInvoiceReview.needs_refresh.is_(True), StripeHistoryBinding.status == "active")
                    .order_by(StripeHistoryInvoiceReview.id).limit(5))).all()
                jobs = [(row.id, row.binding_id, row.stripe_invoice_id) for row in rows]
                if len(jobs) < 5:
                    queued_bindings = {job[1] for job in jobs}
                    dirty = (await db.scalars(select(StripeHistoryBinding).where(StripeHistoryBinding.status == "active",
                        StripeHistoryBinding.needs_refresh.is_(True)).order_by(StripeHistoryBinding.id).limit(5))).all()
                    remaining = [(row.id, row.stripe_subscription_id) for row in dirty if row.id not in queued_bindings][:5-len(jobs)]
                else:
                    remaining = []
            # Subscription-change events have no invoice id. Resolve only the
            # bound subscription's latest invoice; never enumerate an account.
            reader = provider.reader()
            for binding_id, subscription_id in remaining:
                try:
                    remaining_seconds = deadline - asyncio.get_running_loop().time()
                    if remaining_seconds <= 0:
                        break
                    remote = await asyncio.wait_for(reader.subscription(subscription_id), timeout=min(8, remaining_seconds))
                    invoice_id = _id(remote.get("latest_invoice"), "in_")
                    if invoice_id:
                        jobs.append((None, binding_id, invoice_id))
                except Exception:
                    continue
            for review_id, binding_id, invoice_id in jobs[:5]:
                try:
                    remaining_seconds = deadline - asyncio.get_running_loop().time()
                    if remaining_seconds <= 0:
                        break
                    raw = await asyncio.wait_for(reader.invoice(invoice_id), timeout=min(8, remaining_seconds))
                    async with sessions() as db:
                        await lock_sales_workflow(db)
                        binding = await db.get(StripeHistoryBinding, binding_id, populate_existing=True)
                        if not binding or binding.status != "active":
                            continue
                        invoice_created = _instant(raw.get("created"))
                        if not invoice_created or invoice_created.date() < day(binding.sync_from):
                            continue
                        await save_invoice(db, binding, raw)
                        pending = await db.scalar(select(StripeHistoryInvoiceReview.id).where(
                            StripeHistoryInvoiceReview.binding_id == binding.id, StripeHistoryInvoiceReview.needs_refresh.is_(True)).limit(1))
                        binding.needs_refresh = pending is not None
                        binding.last_synced_at = now()
                        await db.commit()
                        processed += 1
                except Exception:
                    # No payload, credential, payer data or response body is
                    # logged. The durable queue survives this bounded attempt.
                    continue
        except Exception:
            return {"processed": processed, "deferred": True}
    return {"processed": processed, "deferred": False}


async def historical_renewal_coverage(db):
    """Read-only adapters for the existing owner overview, grouped per resource.

    A binding means coverage, not health. Actual invoice proof can resolve that
    invoice's old failure; it never clears another invoice or rewrites CRM dates.
    """
    bindings = (await db.scalars(select(StripeHistoryBinding).where(StripeHistoryBinding.account_id == STRIPE_ACCOUNT_ID,
        StripeHistoryBinding.livemode.is_(True), StripeHistoryBinding.status == "active"))).all()
    by_id = {row.id: row for row in bindings}
    grouped = {row.id: {} for row in bindings}
    events = (await db.scalars(select(StripeHistoryEvent).where(StripeHistoryEvent.binding_id.in_(list(by_id))))).all() if bindings else []
    event_groups = {}
    for event in events:
        event_groups.setdefault((event.binding_id, event.resource_key), []).append(event)
    for (binding_id, resource), rows in event_groups.items():
        invoice = resource.startswith("in_")
        terminal = "payment_observed" if invoice else "cancelled"
        terminal_rows = [row for row in rows if row.signal_status == terminal]
        selected = max(terminal_rows or rows, key=lambda row: (utc(row.stripe_created_at),
            1 if row.signal_status == "cancel_scheduled" else 0, row.event_id))
        binding = by_id[binding_id]
        grouped[binding_id][resource] = SimpleNamespace(resource_type="invoice" if invoice else "subscription", resource_key=resource,
            subscription_id=binding.stripe_subscription_id, status=selected.signal_status, latest_event_at=selected.stripe_created_at,
            amount_minor=None, currency=None, due_date=None, period_end=(selected.details or {}).get("period_end"))
    reviews = (await db.scalars(select(StripeHistoryInvoiceReview).where(StripeHistoryInvoiceReview.binding_id.in_(list(by_id))))).all() if bindings else []
    review_links = {}
    for review in reviews:
        binding, value = by_id[review.binding_id], review.snapshot
        review_links.setdefault(binding.id, {})[review.stripe_invoice_id] = review.id
        if value.get("service_minor") is None:
            continue
        previous = grouped[binding.id].get(review.stripe_invoice_id)
        codes = set(value.get("issues", []))
        state = "payment_observed" if not codes else previous.status if previous and previous.status in {"payment_failed", "action_required"} and not (codes & {"refund_or_dispute", "currency_mismatch", "scope_changed"}) else "action_required"
        grouped[binding.id][review.stripe_invoice_id] = SimpleNamespace(resource_type="invoice", resource_key=review.stripe_invoice_id,
            subscription_id=binding.stripe_subscription_id, status=state, latest_event_at=review.observed_at,
            amount_minor=value.get("gross_minor"), currency=value.get("currency"), due_date=None,
            period_end=value.get("coverage_end") if not codes else None)
    result = {}
    for binding in bindings:
        observations = list(grouped[binding.id].values())
        paid_ends = [row.period_end for row in observations if row.status == "payment_observed" and row.period_end]
        target = "/finance?tab=stripe_reconciliation&stripe_view=reviews"
        ranks = {"cancelled": 0, "payment_failed": 1, "action_required": 2, "cancel_scheduled": 3, "watching": 4, "payment_observed": 5}
        urgent = min(observations, key=lambda row: (ranks.get(row.status, 9), utc(row.latest_event_at)), default=None)
        # The action must address the same unresolved resource that caused the
        # warning, never an arbitrary newer paid invoice from that customer.
        review_id = review_links.get(binding.id, {}).get(urgent.resource_key) if urgent else None
        if review_id:
            target += "&stripe_review=" + str(review_id)
        result[binding.crm_subscription_id] = {"binding_id": binding.id, "subscription_id": binding.stripe_subscription_id,
            "observations": observations, "period_end": max(paid_ends) if paid_ends else None, "href": target}
    return {"by_crm_subscription": result, "subscription_ids": {row.stripe_subscription_id for row in bindings},
        "received_event_count": len(events), "latest_event_at": max([utc(row.stripe_created_at) for row in events] + [utc(row.observed_at) for row in reviews], default=None)}
