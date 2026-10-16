"""Fixed-price sale registration, with separate receipt and delivery verification.

This service deliberately never calls the legacy quote approval/conversion flow.
Registration creates no Payments. Only owner verification calls the existing
payment synchronizer, in the same transaction as the immutable handoff receipt.
"""
import hashlib
import calendar
import json
import math
import re
from datetime import date, datetime, time, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import or_, select

from models.customer_contacts import Customer_contacts
from models.commissions import CustomerCommissionAttribution, SalesPartner
from models.customers import Customers
from models.deals import Deals
from models.employees import Employees
from models.management_decisions import BusinessLine, CustomerEngagement, EngagementSourceLink, ProductCatalog, ProductPlan
from models.sales_call_activities import SalesCallActivities
from models.sales_deal_controls import SalesQuoteRequests
from models.sales_deal_handoffs import SalesDealHandoff, SalesDealPlanPolicy
from models.sales_dossiers import SalesDossierSummary
from models.sales_lead_conversion_logs import SalesLeadConversionLogs
from models.sales_leads import SalesLeads
from models.payments import Payments
from models.subscriptions import Subscriptions
from services.commissions import auto_assign_new_customer
from services.customer_permissions import FINANCE_LEVELS, get_customer_permissions, is_customer_owner
from services.deal_payment_sync import sync_payment_from_deal
from services.phone_numbers import parse_phone_number, phone_match_key
from services.sales_enrichment import get_enrichment
from services.sales_workflow_locks import lock_sales_workflow

PLATFORMS = ("Google Business Profile", "Google Ads", "Meta Ads", "Facebook", "Instagram", "TikTok", "Yelp", "小红书", "官网")
OPS_ROLES = ("operations", "operations_manager")
CYCLES = ("monthly", "quarterly", "semi_annual", "annual", "one_time")
PERIOD_MONTHS = {"monthly": 1, "quarterly": 3, "semi_annual": 6, "annual": 12, "one_time": None}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode()).hexdigest()


def stamp():
    return datetime.now(timezone.utc)


def moment(day):
    return datetime.combine(day, time.min, timezone.utc) if day else None


def plan_data(plan, product, line, policy=None):
    value = {"id": plan.id, "product_id": product.id, "business_line_id": line.id, "plan_code": plan.code,
        "name": plan.name, "standard_price": plan.standard_price,
        "default_currency": plan.default_currency, "default_billing_cycle": plan.default_billing_cycle,
        "platform_limit": plan.platform_limit, "scope_type": plan.scope_type,
        "product_name": product.name, "business_line_code": line.code,
        "required_collection_method": policy.collection_policy if policy else "manual",
        "service_period_months": PERIOD_MONTHS[plan.default_billing_cycle]}
    value["catalog_token"] = digest({**value, "plan_updated_at": plan.updated_at,
        "product_updated_at": product.updated_at, "line_updated_at": line.updated_at,
        "policy_revision": policy.revision if policy else 0, "policy_updated_at": policy.updated_at if policy else None})
    from services.sales_payment_catalog import catalog_link
    value["payment_link"] = catalog_link(value)
    return value


async def catalog(db):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    rows = (await db.execute(select(ProductPlan, ProductCatalog, BusinessLine)
        .join(ProductCatalog, ProductCatalog.id == ProductPlan.product_id)
        .join(BusinessLine, BusinessLine.id == ProductCatalog.business_line_id)
        .where(BusinessLine.is_active.is_(True), ProductCatalog.is_active.is_(True),
            ProductPlan.is_active.is_(True), ProductPlan.pricing_status == "published",
            ProductPlan.standard_price.is_not(None), ProductPlan.standard_price >= 0,
            or_(ProductCatalog.effective_from.is_(None), ProductCatalog.effective_from <= today),
            or_(ProductCatalog.effective_to.is_(None), ProductCatalog.effective_to >= today),
            or_(ProductPlan.effective_from.is_(None), ProductPlan.effective_from <= today),
            or_(ProductPlan.effective_to.is_(None), ProductPlan.effective_to >= today))
        .order_by(BusinessLine.id, ProductCatalog.id, ProductPlan.id))).all()
    policies = {row.plan_id: row for row in (await db.scalars(select(SalesDealPlanPolicy))).all()}
    lines, products, plans = {}, {}, []
    for plan, product, line in rows:
        price = Decimal(str(plan.standard_price))
        policy = policies.get(plan.id)
        if (not math.isfinite(float(plan.standard_price)) or price > 1000000
                or (price.is_finite() and price != price.quantize(Decimal("0.01")))
                or not re.fullmatch(r"[A-Z]{3}", plan.default_currency or "")
                or (policy is not None and policy.collection_policy not in {"manual", "stripe_auto"})
                or plan.default_billing_cycle not in CYCLES):
            continue
        lines[line.id] = {"id": line.id, "code": line.code, "name": line.name}
        products[product.id] = {"id": product.id, "business_line_id": line.id, "name": product.name}
        plans.append(plan_data(plan, product, line, policy))
    return {"business_lines": list(lines.values()), "products": list(products.values()), "plans": plans,
        "platform_options": list(PLATFORMS), "status": "ready" if plans else "no_published_prices",
        "message": None if plans else "暂无已发布且有效的统一价格套餐，请老板先维护产品价格；系统不会补造价格。"}


def period_end(start, billing_cycle):
    months = PERIOD_MONTHS[billing_cycle]
    if months is None:
        return None
    target = start.year * 12 + start.month - 1 + months
    year, month = target // 12, target % 12 + 1
    if year > 9999:
        raise HTTPException(422, "服务日期超出可支持范围，请核对真实服务日期")
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def policy_data(row):
    return {"plan_id": row.plan_id, "collection_policy": row.collection_policy, "revision": row.revision,
        "updated_by_id": row.updated_by_id, "updated_by_name": row.updated_by_name, "updated_at": row.updated_at}


async def policies(db, user):
    if not is_customer_owner(user):
        raise HTTPException(403, "统一价格收款方式仅老板可维护")
    return {"items": [policy_data(row) for row in (await db.scalars(select(SalesDealPlanPolicy).order_by(SalesDealPlanPolicy.plan_id))).all()],
            "default_collection_policy": "manual"}


async def save_policy(db, plan_id, payload, user):
    if not is_customer_owner(user):
        raise HTTPException(403, "统一价格收款方式仅老板可维护")
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    plan = await db.get(ProductPlan, plan_id, populate_existing=True)
    if not plan:
        raise HTTPException(404, "套餐不存在")
    if payload.collection_policy == "stripe_auto" and plan.default_billing_cycle == "one_time":
        raise HTTPException(400, "一次性套餐不能配置为自动订阅价")
    row = await db.get(SalesDealPlanPolicy, plan_id, populate_existing=True)
    if row is None:
        row = SalesDealPlanPolicy(plan_id=plan_id, revision=0)
        db.add(row)
    if row.collection_policy != payload.collection_policy:
        row.revision += 1
        row.collection_policy = payload.collection_policy
        row.updated_by_id, row.updated_by_name, row.updated_at = int(user.id), user.name, stamp()
    await db.flush()
    return policy_data(row)


async def scoped_lead(db, lead_id, user):
    from routers.sales_deal_controls import _ensure_sales_access, _get_scoped_lead
    _ensure_sales_access(user)
    return await _get_scoped_lead(db, lead_id, user)


async def source_data(db, lead):
    enrichment = await get_enrichment(db, lead)
    summary = await db.get(SalesDossierSummary, lead.id)
    calls = (await db.scalars(select(SalesCallActivities).where(SalesCallActivities.lead_id == lead.id)
                             .order_by(SalesCallActivities.called_at, SalesCallActivities.id))).all()
    # Whitelist sales context. Never carry untyped event payloads or financial records.
    return {"lead_id": lead.id, "lead_notes": lead.notes, "business_name": lead.business_name,
        "contacts": enrichment["contacts"], "preferred_contact_id": enrichment["preferred_contact_id"],
        "interest_product_ids": enrichment["interest_product_ids"], "need_summary": enrichment["need_summary"],
        "best_contact_time": enrichment["best_contact_time"],
        "summary": {key: value for key, value in (summary.payload if summary else {}).items()
                    if key in {"need_summary", "concerns", "promises", "next_action", "decision_maker", "best_contact_time",
                               "latest_conclusion", "objections", "next_step"}},
        "history": [{"id": row.id, "notes": row.notes, "outcome": row.outcome,
                     "called_at": str(row.called_at), "sales_employee_name": row.sales_employee_name,
                     "next_follow_up_at": str(row.next_follow_up_at) if row.next_follow_up_at else None} for row in calls]}


async def history_access(db, lead_id, user):
    from services.sales_dossiers import authorize_dossier
    try:
        await authorize_dossier(db, lead_id, user)
        return True
    except HTTPException:
        return False


async def receipt(db, row, user, *, sales=False):
    rights = await get_customer_permissions(db, user, row.customer_id)
    can_view = any(item["read"] for item in rights["modules"].values())
    finance = FINANCE_LEVELS.index(rights["finance_access"]) >= FINANCE_LEVELS.index("receipts")
    history = await history_access(db, row.lead_id, user)
    actor = await db.get(Employees, int(user.id))
    can_ack = bool(actor and actor.status in {"active", "probation"} and actor.role in OPS_ROLES
                   and actor.id == row.operations_owner_employee_id and rights["modules"]["delivery"]["read"])
    owner = await db.get(Employees, row.operations_owner_employee_id)
    ops_rights = await get_customer_permissions(db, SimpleNamespace(id=owner.id, role=owner.role, name=owner.name), row.customer_id) if owner else None
    delivery = sales or rights["modules"]["delivery"]["read"]
    deals = sales or rights["modules"]["deals"]["read"]
    contacts = sales or rights["modules"]["contacts"]["read"]
    followups = sales or rights["modules"]["followups"]["read"]
    data = {"id": row.id, "customer_id": row.customer_id,
        "customer_access_status": "authorized" if can_view else "pending", "can_view_customer": can_view,
        "can_view_history": history, "history_url": f"/sales-leads?dossier={row.lead_id}" if history else None,
        "can_finance_confirm": is_customer_owner(user) and row.payment_status != "paid",
        "can_operations_ack": can_ack and row.operations_status != "accepted", "created_at": row.created_at}
    from services.sales_deal_payments import can_request_payment, handoff_link
    payment_sender = await can_request_payment(db, row, user)
    data["can_request_payment"] = bool(row.payment_status != "paid" and handoff_link(row)
        and payment_sender)
    data["can_view_payment_observations"] = is_customer_owner(user)
    # Operational progress for this seller's handoff, not customer financial
    # access: no amounts received, receipt IDs, payer identity or tax data.
    if is_customer_owner(user) or (sales and payment_sender):
        data["receipt_review_status"] = "owner_verified" if row.payment_status == "paid" else "pending_owner_review"
    created = row.created_at.replace(tzinfo=timezone.utc) if row.created_at and row.created_at.tzinfo is None else row.created_at
    data["waiting_days"] = max(0, (stamp() - created).days) if created else 0
    if deals or delivery:
        data.update(lead_id=row.lead_id, engagement_id=row.engagement_id, deal_id=row.deal_id,
            subscription_id=row.subscription_id, package_name=row.plan_snapshot["name"],
            billing_cycle=row.plan_snapshot["default_billing_cycle"])
    if delivery:
        data.update(operations_owner_employee_id=row.operations_owner_employee_id,
            operations_owner_name=row.operations_owner_name, operations_status=row.operations_status,
            operations_acknowledged_at=row.operations_acknowledged_at,
            operations_access_status="authorized" if ops_rights and ops_rights["modules"]["delivery"]["read"] else "pending")
    if sales:
        # The agreed sale price is not a verification of received funds.
        data.update(amount=row.amount, currency=row.currency, collection_method=row.collection_method)
    if finance:
        data.update(amount=row.amount, currency=row.currency, collection_method=row.collection_method,
                    payment_status=row.payment_status)
    elif rights["finance_access"] == "status":
        data["payment_status"] = row.payment_status
    if finance:
        data.update(payment_id=row.payment_id, payment_confirmed_at=row.payment_confirmed_at,
                    payment_confirmed_by_name=row.payment_confirmed_by_name)
    source = {}
    if delivery:
        source.update({key: row.source_snapshot.get(key) for key in
            ("customer_goal", "handoff_notes", "special_commitments", "selected_platforms", "service_start_date", "service_end_date")})
        data["operations_ack_note"] = row.operations_ack_note
    if contacts:
        source.update(contacts=row.source_snapshot.get("contacts", []), preferred_contact_id=row.source_snapshot.get("preferred_contact_id"))
    if followups:
        source.update({key: row.source_snapshot.get(key) for key in
            ("lead_notes", "need_summary", "interest_product_ids", "best_contact_time", "summary", "history")})
    if source:
        data["source"] = source
    return data


async def lead_status(db, lead_id, user):
    lead = await scoped_lead(db, lead_id, user)
    row = await db.scalar(select(SalesDealHandoff).where(SalesDealHandoff.lead_id == lead.id))
    source = await source_data(db, lead)
    reason = None
    if lead.is_blacklisted or lead.do_not_contact:
        reason = "此商家禁止联系，不能登记成交"
    elif row:
        reason = "此商家已登记成交；后续合作请从已授权的客户流程处理"
    elif lead.converted_customer_id:
        reason = "此商家已通过旧流程转为客户，请从已授权的客户流程处理"
    elif not (lead.contact_name or "").strip():
        reason = "请先完善联系人姓名"
    employees = (await db.scalars(select(Employees).where(Employees.status.in_(["active", "probation"]),
        Employees.role.in_(OPS_ROLES)).order_by(Employees.name))).all()
    quotes = (await db.scalars(select(SalesQuoteRequests).where(SalesQuoteRequests.lead_id == lead.id)
                              .order_by(SalesQuoteRequests.id.desc()))).all()
    history = await history_access(db, lead_id, user)
    return {"registered": row is not None, "can_register": reason is None, "read_only_reason": reason,
        "can_view_history": history, "history_url": f"/sales-leads?dossier={lead_id}" if history else None,
        "lead": {"id": lead.id, "business_name": lead.business_name, "contact_name": lead.contact_name, "phone": lead.phone},
        "operations_candidates": [{"id": item.id, "name": item.name} for item in employees],
        "contacts": source["contacts"], "preferred_contact_id": source["preferred_contact_id"],
        "customer_goal": source["need_summary"] or source["summary"].get("need_summary", ""),
        "summary": source["summary"], "handoff": await receipt(db, row, user, sales=True) if row else None,
        "legacy_quotes": [{"id": quote.id, "package_name": quote.package_name, "final_amount": quote.final_amount,
            "currency": quote.currency, "status": quote.status, "created_at": quote.created_at} for quote in quotes]}


def _valid_contacts(source, lead):
    result = []
    for item in source["contacts"]:
        if not isinstance(item, dict):
            continue
        phone = item.get("phone")
        if not phone and item.get("id") == f"legacy-{lead.id}":
            phone = lead.phone
        if phone:
            parsed = parse_phone_number(phone, lead.country)
            if not parsed.is_valid or parsed.extension:
                if item.get("id") == source["preferred_contact_id"]:
                    raise HTTPException(400, "主联系人电话尚未核实，请先修正主联系人号码；副联系人原资料会保留待核实")
                raw_phone, phone = phone, None
            else:
                raw_phone, phone = None, parsed.e164
        else:
            raw_phone = None
        if item.get("name") or phone or raw_phone or item.get("email") or item.get("wechat"):
            result.append({key: item.get(key) for key in ("id", "name", "role", "email", "wechat", "verification")} |
                          {"phone": phone, "raw_phone": raw_phone, "verification": "pending" if raw_phone else item.get("verification")})
    if not result:
        result.append({"id": f"legacy-{lead.id}", "name": lead.contact_name, "phone": lead.phone,
                       "role": "销售线索联系人", "verification": "pending", "email": None, "wechat": None})
    return result


async def _copy_contacts(db, customer, contacts, lead):
    old = (await db.scalars(select(Customer_contacts).where(Customer_contacts.customer_id == customer.id))).all()
    identities = {(item.contact_name.strip().casefold(), phone_match_key(item.contact_phone, customer.country) or item.contact_phone or "") for item in old}
    for item in contacts:
        name = (item.get("name") or "未填写姓名的联系人").strip()
        key = (name.casefold(), phone_match_key(item.get("phone"), lead.country) or item.get("phone") or "")
        metadata = json.dumps({"source": "sales_deal_handoff", "lead_id": lead.id,
            "email": item.get("email"), "wechat": item.get("wechat"), "raw_phone": item.get("raw_phone"),
            "verification": item.get("verification")}, ensure_ascii=False)
        # Equal name/no-phone entries may carry distinct e-mail/WeChat; compare metadata too.
        if key in identities and (key[1] or any(row.contact_name == name and row.notes == metadata for row in old)):
            continue
        row = Customer_contacts(customer_id=customer.id, contact_name=name, contact_phone=item.get("phone"),
            contact_role=item.get("role"), notes=metadata, created_at=stamp())
        db.add(row)
        old.append(row)
        identities.add(key)


def _financial_product_type(plan, platforms):
    # Preserve the existing payment synchronizer's recognized product vocabulary.
    from routers.sales_leads import _quote_product_type
    if plan["business_line_code"] in {"restaurant_os", "beauty_os"}:
        return plan["business_line_code"]
    # A Google Ads platform label is not itself a second sale of social media.
    result = _quote_product_type(plan["name"], None)
    if result == "combo":
        raise HTTPException(400, "该套餐含多类收入，请先由老板明确独立套餐和财务分类后登记；系统不会猜测拆分")
    return result


async def register(db, lead_id, payload, user):
    await lock_sales_workflow(db, lead_ids=[lead_id], employee_ids=[int(user.id), payload.operations_owner_employee_id])
    lead = await scoped_lead(db, lead_id, user)
    payload_data = payload.model_dump(mode="json", exclude={"idempotency_key"})
    fingerprint = digest(payload_data)
    row = await db.scalar(select(SalesDealHandoff).where(SalesDealHandoff.lead_id == lead.id))
    if row:
        if row.payload_digest != fingerprint:
            raise HTTPException(409, "此商家已登记成交，本次没有重复创建；请查看已登记记录")
        return {"registered": True, "idempotent_replay": True, "handoff": await receipt(db, row, user, sales=True)}
    if await db.scalar(select(SalesDealHandoff.id).where(SalesDealHandoff.idempotency_key == payload.idempotency_key)):
        raise HTTPException(409, "该请求编号已使用，请重新打开本商家的登记表")
    if lead.converted_customer_id or lead.is_blacklisted or lead.do_not_contact:
        raise HTTPException(409, "商家已转客户或禁止联系，本次未登记")
    if not (lead.contact_name or "").strip():
        raise HTTPException(400, "请先完善联系人姓名")
    # Lock the sellable version while taking its authoritative price snapshot.
    await db.scalar(select(ProductPlan).where(ProductPlan.id == payload.plan_id).with_for_update()
                    .execution_options(populate_existing=True))
    data = await catalog(db)
    plan = next((item for item in data["plans"] if item["id"] == payload.plan_id), None)
    if not plan or plan["catalog_token"] != payload.catalog_token:
        raise HTTPException(409, "统一价格或套餐有效状态已更新，请刷新套餐后核对；本次没有登记")
    platforms = list(dict.fromkeys(payload.selected_platforms))
    if set(platforms) - set(PLATFORMS):
        raise HTTPException(400, "服务平台不在当前标准选项中")
    if plan["platform_limit"] and len(platforms) > plan["platform_limit"]:
        raise HTTPException(400, "所选平台数量超过套餐上限")
    expected_end = period_end(payload.service_start_date, plan["default_billing_cycle"])
    if payload.service_end_date and expected_end and payload.service_end_date != expected_end:
        raise HTTPException(400, f"套餐收费周期与服务结束日不一致，应为 {expected_end.isoformat()}；本次未登记")
    service_end = expected_end or payload.service_end_date
    if plan["required_collection_method"] == "stripe_auto" and payload.collection_method != "stripe_auto":
        raise HTTPException(400, "该统一价格仅适用于 Stripe 自动订阅，不能切换为人工收款优惠价")
    if plan["required_collection_method"] == "manual" and payload.collection_method == "stripe_auto":
        raise HTTPException(400, "该统一价格适用于人工收款，请选择支票、银行、Zelle 或其他人工方式")
    if plan["default_billing_cycle"] == "one_time" and payload.collection_method == "stripe_auto":
        raise HTTPException(400, "一次性套餐不能登记为自动订阅；请选择实际收款方式")
    if service_end and service_end <= payload.service_start_date:
        raise HTTPException(400, "服务结束日期必须晚于开始日期")
    operator = await db.get(Employees, payload.operations_owner_employee_id, populate_existing=True)
    if not operator or operator.status not in {"active", "probation"} or operator.role not in OPS_ROLES:
        raise HTTPException(400, "请选择在职运营员工接收；老板不能代运营本人接收")
    product_type = _financial_product_type(plan, platforms)
    from routers.sales_leads import _find_customer_duplicates
    matches = await _find_customer_duplicates(db, lead)
    customer = None
    if payload.existing_customer_id:
        if not is_customer_owner(user):
            raise HTTPException(403, "关联已有客户需要老板确认")
        customer = await db.get(Customers, payload.existing_customer_id)
        if not customer:
            raise HTTPException(404, "客户不存在")
    elif matches:
        raise HTTPException(409, "此商家可能已有正式客户，请老板核对后关联；本次未重复新增")
    source = await source_data(db, lead)
    source["contacts"] = _valid_contacts(source, lead)
    source.update(customer_goal=payload.customer_goal, handoff_notes=payload.handoff_notes,
                  special_commitments=payload.special_commitments, confirmation_notes=payload.confirmation_notes,
                  selected_platforms=platforms, service_start_date=str(payload.service_start_date),
                  service_end_date=str(service_end) if service_end else None)
    now = stamp()
    new_customer = customer is None
    if new_customer:
        preferred = next((item for item in source["contacts"] if item.get("id") == source["preferred_contact_id"]), source["contacts"][0])
        customer = Customers(customer_code=f"C{now:%Y%m%d}-{uuid4().hex[:10].upper()}", sales_lead_id=lead.id,
            **{key: getattr(lead, key) for key in ("business_name", "contact_name", "phone", "address", "city", "state", "country", "industry", "website", "source")},
            email=preferred.get("email"), wechat=preferred.get("wechat"),
            sales_person=lead.assigned_sales_name, sales_employee_id=lead.assigned_sales_id, status="closed",
            notes=f"销售线索 #{lead.id} 统一价格成交登记。需求：{payload.customer_goal}。交接：{payload.handoff_notes or ''}",
            created_at=now, updated_at=now)
        db.add(customer)
        await db.flush()
        link = await auto_assign_new_customer(db, customer_id=customer.id, sales_employee_id=lead.assigned_sales_id,
            effective_from=min(datetime.now(ZoneInfo("Asia/Shanghai")).date(), payload.service_start_date),
            actor_id=str(user.id), actor_name=user.name)
        if link is None:
            raise HTTPException(409, "分润归属基础尚未准备完成，请老板检查后再登记；本次没有创建客户")
        partner = await db.get(SalesPartner, link.partner_id)
        # Only the attribution just created for this new customer is initialized.
        # Existing customer links/agreements/rates are never rewritten here.
        link.commission_mode = "none" if partner.partner_type == "direct" else "first_month_then_renewal"
        link.commission_start_date = payload.service_start_date
        link.first_service_start = payload.service_start_date
    source["new_customer"] = new_customer
    await _copy_contacts(db, customer, source["contacts"], lead)
    engagement = CustomerEngagement(customer_id=customer.id, business_line_id=plan["business_line_id"],
        product_id=plan["product_id"], product_plan_id=plan["id"], engagement_code=f"ENG-{uuid4().hex.upper()}",
        package_name=plan["name"], status="pending_setup", owner_employee_id=operator.id,
        sales_employee_id=lead.assigned_sales_id, billing_cycle=plan["default_billing_cycle"],
        collection_method=payload.collection_method, currency=plan["default_currency"],
        selected_platforms=json.dumps(platforms, ensure_ascii=False),
        service_scope_json=json.dumps({"sales_handoff": {"lead_id": lead.id, "customer_goal": payload.customer_goal,
            "handoff_notes": payload.handoff_notes, "special_commitments": payload.special_commitments}}, ensure_ascii=False),
        created_at=now, updated_at=now)
    db.add(engagement)
    await db.flush()
    deal = Deals(customer_id=customer.id, customer_name=customer.business_name, engagement_id=engagement.id,
        business_line_id=plan["business_line_id"], product_id=plan["product_id"], product_plan_id=plan["id"],
        sales_employee_id=lead.assigned_sales_id, sales_name=lead.assigned_sales_name, product_type=product_type,
        package_name=plan["name"], package_platforms=json.dumps(platforms, ensure_ascii=False),
        billing_cycle=plan["default_billing_cycle"], deal_amount=plan["standard_price"], is_paid=False,
        service_start_date=moment(payload.service_start_date), service_end_date=moment(service_end),
        is_handed_over=False, is_transferred_ops=False, needs_group=True,
        notes=f"统一价格成交登记；来源销售线索 #{lead.id}；实际收款以独立核对记录为准。", deal_date=now, created_at=now)
    db.add(deal)
    await db.flush()
    subscription = None
    if plan["default_billing_cycle"] != "one_time":
        subscription = Subscriptions(customer_id=customer.id, customer_name=customer.business_name,
            deal_id=deal.id, engagement_id=engagement.id, business_line_id=plan["business_line_id"],
            product_id=plan["product_id"], product_plan_id=plan["id"], package_name=plan["name"],
            package_price=plan["standard_price"], list_price_snapshot=plan["standard_price"], pricing_source="published_plan",
            selected_platforms=json.dumps(platforms, ensure_ascii=False), billing_cycle=plan["default_billing_cycle"],
            start_date=moment(payload.service_start_date), end_date=moment(service_end),
            auto_renew=False, renewal_person=lead.assigned_sales_name, status="pending",
            renewal_result="awaiting_verified_payment", created_at=now, updated_at=now)
        db.add(subscription)
        await db.flush()
    row = SalesDealHandoff(lead_id=lead.id, customer_id=customer.id, engagement_id=engagement.id,
        deal_id=deal.id, subscription_id=subscription.id if subscription else None,
        idempotency_key=payload.idempotency_key, payload_digest=fingerprint, catalog_token=payload.catalog_token,
        plan_snapshot=plan, source_snapshot=source, amount=plan["standard_price"], currency=plan["default_currency"],
        collection_method=payload.collection_method, operations_owner_employee_id=operator.id,
        operations_owner_name=operator.name, operations_status="pending", payment_status="pending",
        registered_by_id=int(user.id), registered_by_name=user.name, created_at=now)
    db.add(row)
    await db.flush()
    db.add(EngagementSourceLink(engagement_id=engagement.id, source_type="sales_lead", source_id=lead.id,
        link_role="sale_registration", confidence="confirmed", linked_by_id=str(user.id), linked_by_name=user.name,
        note=f"统一价格成交交接 #{row.id}"))
    db.add(SalesLeadConversionLogs(lead_id=lead.id, customer_id=customer.id, generated_customer_code=customer.customer_code or f"existing-{customer.id}",
        duplicate_check_json=json.dumps({"checked": True, "linked_existing": not new_customer}),
        lead_snapshot_json=json.dumps({"source": "fixed_catalog_sale", "handoff_id": row.id, "source_snapshot": source}, ensure_ascii=False),
        generate_service_board=False, converted_by_id=int(user.id), converted_by_name=user.name))
    lead.converted_customer_id, lead.converted_at = customer.id, now
    lead.converted_by_id, lead.converted_by_name, lead.status = int(user.id), user.name, "won"
    await db.flush()
    return {"registered": True, "idempotent_replay": False, "handoff": await receipt(db, row, user, sales=True)}


async def customer_handoffs(db, customer_id, user):
    rights = await get_customer_permissions(db, user, customer_id)
    if not any(item["read"] for item in rights["modules"].values()):
        raise HTTPException(404, "客户不存在或尚未授权")
    if not any(rights["modules"][key]["read"] for key in ("deals", "delivery", "contacts", "followups")):
        return {"items": []}
    rows = (await db.scalars(select(SalesDealHandoff).where(SalesDealHandoff.customer_id == customer_id)
                            .order_by(SalesDealHandoff.id.desc()))).all()
    return {"items": [await receipt(db, row, user) for row in rows]}


async def finance_confirm(db, handoff_id, payload, user):
    if not is_customer_owner(user):
        raise HTTPException(403, "收款核对仅老板可操作；销售登记不代表财务核款")
    await lock_sales_workflow(db)
    row = await db.get(SalesDealHandoff, handoff_id, populate_existing=True)
    if not row:
        raise HTTPException(404, "成交交接不存在")
    # Optional evidence fields are omitted for backwards-compatible replay of
    # receipts verified before the independent tax/fee evidence was introduced.
    fingerprint = digest(payload.model_dump(mode="json", exclude_none=True))
    if row.payment_status == "paid":
        if row.payment_fingerprint != fingerprint:
            raise HTTPException(409, "收款已核对，本次没有覆盖原凭证；更正请使用原财务流程")
        return {"idempotent_replay": True, "handoff": await receipt(db, row, user)}
    if Decimal(str(payload.amount_received)).quantize(Decimal("0.01")) != Decimal(str(row.amount)).quantize(Decimal("0.01")):
        raise HTTPException(400, "第一版仅支持本次套餐全额核款；订金或金额不符不能标记为已收款")
    if payload.payment_date > datetime.now(ZoneInfo("Asia/Shanghai")).date():
        raise HTTPException(400, "实际收款日期不能在未来")
    if row.currency != payload.currency:
        raise HTTPException(400, "收款币种与登记套餐不一致")
    required_collection = row.plan_snapshot.get("required_collection_method", "manual")
    if required_collection == "stripe_auto" and payload.payment_method != "stripe":
        raise HTTPException(400, "登记的自动订阅应核对 Stripe 收款；请先核实收款方式")
    if required_collection == "manual" and payload.payment_method == "stripe":
        raise HTTPException(400, "本次冻结的是人工收款价格，不能改成 Stripe 订阅收款")
    if row.source_snapshot.get("new_customer"):
        attribution = await db.scalar(select(CustomerCommissionAttribution).where(
            CustomerCommissionAttribution.customer_id == row.customer_id,
            CustomerCommissionAttribution.effective_from <= payload.payment_date,
            or_(CustomerCommissionAttribution.effective_to.is_(None), CustomerCommissionAttribution.effective_to >= payload.payment_date)))
        if not attribution:
            raise HTTPException(409, "收款日期早于本次客户分润归属生效日，请老板先核对真实日期和已有归属流程；本次未记账")
    deal = await db.get(Deals, row.deal_id, populate_existing=True)
    if not deal or deal.customer_id != row.customer_id or deal.engagement_id != row.engagement_id or deal.is_paid:
        raise HTTPException(409, "成交关联或支付状态已变更，请先由老板核对，未生成收款")
    if Decimal(str(deal.deal_amount)) != Decimal(str(row.amount)):
        raise HTTPException(409, "成交金额已变更，请先核对，未生成收款")
    # Do not silently reuse/overwrite a separately entered receipt for this sale.
    candidates = (await db.scalars(select(Payments).where(Payments.customer_id == row.customer_id,
        or_(Payments.source_deal_id == row.deal_id,
            (Payments.source_deal_id.is_(None)) & (Payments.product_name == deal.package_name)
            & (Payments.amount_due == deal.deal_amount))))).all()
    if candidates:
        raise HTTPException(409, "已有可能关联的收款，请先从原财务流程核对关联，避免重复记账或覆盖凭证")
    from services.sales_deal_payments import prepare_receipt_evidence
    await prepare_receipt_evidence(db, row, payload, user)
    deal.is_paid = True
    row.payment_status = "verifying"
    await db.flush()
    payment = await sync_payment_from_deal(db, deal, commit=False, amount_paid_override=row.amount,
        payment_method_override=payload.payment_method,
        payment_mode_override="subscription_auto" if row.collection_method == "stripe_auto" else "manual_collection",
        currency_override=row.currency, transaction_reference_override=payload.transaction_reference,
        payment_date_override=moment(payload.payment_date))
    payment.engagement_id, payment.business_line_id = row.engagement_id, deal.business_line_id
    payment.product_id = deal.product_id
    project = await db.get(CustomerEngagement, row.engagement_id)
    project.status, project.paid_started_at, project.updated_at = "active_paid", moment(payload.payment_date), stamp()
    if row.subscription_id:
        subscription = await db.get(Subscriptions, row.subscription_id)
        subscription.status, subscription.last_payment_date = "active", moment(payload.payment_date)
        subscription.next_payment_date = subscription.end_date
        # This is a CRM flag, not a request to Stripe to create/charge a subscription.
        subscription.auto_renew = row.collection_method == "stripe_auto"
        subscription.renewal_result, subscription.updated_at = "initial_payment_verified", stamp()
    row.payment_id, row.payment_status, row.payment_fingerprint = payment.id, "paid", fingerprint
    row.payment_confirmed_by_id, row.payment_confirmed_by_name = int(user.id), user.name
    row.payment_confirmed_at = stamp()
    await db.flush()
    return {"idempotent_replay": False, "handoff": await receipt(db, row, user)}


async def operations_ack(db, handoff_id, payload, user):
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    row = await db.get(SalesDealHandoff, handoff_id, populate_existing=True)
    actor = await db.get(Employees, int(user.id), populate_existing=True)
    if not row:
        raise HTTPException(404, "成交交接不存在")
    if not actor or actor.status not in {"active", "probation"} or actor.role not in OPS_ROLES or actor.id != row.operations_owner_employee_id:
        raise HTTPException(403, "只能由指定的运营本人确认接收，老板或其他员工不能代收")
    rights = await get_customer_permissions(db, user, row.customer_id)
    if not rights["modules"]["delivery"]["read"]:
        raise HTTPException(403, "客户交付资料尚未授权，请老板先邀请后由运营本人接收")
    if row.operations_status != "accepted":
        row.operations_status, row.operations_acknowledged_at = "accepted", stamp()
        row.operations_ack_note = payload.note
        deal = await db.get(Deals, row.deal_id)
        deal.is_handed_over, deal.is_transferred_ops = True, True
        await db.flush()
    return {"handoff": await receipt(db, row, user)}


async def get_handoff(db, handoff_id, user):
    row = await db.get(SalesDealHandoff, handoff_id)
    if not row:
        raise HTTPException(404, "成交交接不存在或尚未授权")
    actor = await db.get(Employees, int(user.id))
    sales = False
    if str(user.role) in {"super_admin", "admin", "sales_manager", "sales"}:
        try:
            await scoped_lead(db, row.lead_id, user)
            sales = True
        except HTTPException:
            pass
    if not sales:
        rights = await get_customer_permissions(db, user, row.customer_id)
        if not actor or actor.role not in OPS_ROLES or actor.id != row.operations_owner_employee_id or not rights["modules"]["delivery"]["read"]:
            raise HTTPException(404, "成交交接不存在或尚未授权")
    return {"registered": True, "handoff": await receipt(db, row, user, sales=sales)}


async def queue(db, user, status="all"):
    query = select(SalesDealHandoff).join(SalesLeads, SalesLeads.id == SalesDealHandoff.lead_id)
    owner = is_customer_owner(user)
    role = str(user.role)
    if not owner:
        if role in OPS_ROLES:
            query = query.where(SalesDealHandoff.operations_owner_employee_id == int(user.id))
        elif role == "sales":
            query = query.where(SalesLeads.assigned_sales_id == int(user.id))
        elif role in {"sales_manager", "admin"}:
            # Scope each row using the same team authority as sale registration.
            pass
        else:
            raise HTTPException(403, "无权查看成交交接队列")
    rows = (await db.scalars(query.order_by(SalesDealHandoff.id.desc()))).all()
    items = []
    for row in rows:
        try:
            item = (await get_handoff(db, row.id, user))["handoff"]
        except HTTPException as error:
            if error.status_code in {403, 404}:
                continue
            raise
        item["business_name"] = row.source_snapshot.get("business_name")
        # Counts may reveal status only within the same authorized row scope.
        item["pending_payment"] = (item.get("receipt_review_status") == "pending_owner_review"
            if "receipt_review_status" in item else row.payment_status != "paid" if "payment_status" in item else False)
        item["pending_operations"] = row.operations_status != "accepted"
        item["pending_access"] = item.get("operations_access_status") == "pending" if owner else False
        item.pop("source", None)
        items.append(item)
    counts = {"all": len(items), **{name: sum(bool(item[name]) for item in items)
        for name in ("pending_payment", "pending_operations", "pending_access")}}
    counts["completed"] = sum(not any(item[key] for key in ("pending_payment", "pending_operations", "pending_access")) for item in items)
    if status == "completed":
        items = [item for item in items if not any(item[key] for key in ("pending_payment", "pending_operations", "pending_access"))]
    elif status != "all":
        items = [item for item in items if item[status]]
    return {"items": items, "counts": counts, "total": len(items), "is_owner": owner, "status": status}
