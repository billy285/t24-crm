"""Sales-only Stripe observations. No Stripe API writes, ledger writes or grants.

A signed Checkout event is evidence awaiting the owner's verification, never
proof of the payer/customer identity, a service start date or a verified receipt.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import time
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy import or_, select

from models.employees import Employees
from models.sales_deal_handoffs import SalesDealHandoff
from models.sales_deal_payments import SalesPaymentRequest, SalesReceiptEvidence, SalesStripeEvent, SalesStripeObservation
from models.sales_leads import SalesLeads
from models.subscriptions import Subscriptions
from services.customer_permissions import is_customer_owner
from services.sales_payment_catalog import CADENCES, STRIPE_ACCOUNT_ID, approved_link
from services.sales_workflow_locks import lock_sales_workflow

DUPLICATE_SCOPE = "仅检查 CRM 已在服订阅及本接入已收到的 Stripe 记录，未查询 Stripe 全部历史；关联编号不证明付款人身份。"
EVENT_TYPES = {
    "checkout.session.completed", "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed", "checkout.session.expired",
}
MAX_BODY_BYTES = 262144
DEFAULT_WEBHOOK_SECRET_FILE = "/app/backend/data/sales-stripe-webhook-secret"


def webhook_secret():
    """Independent CRM secret; a protected file can be provisioned out of band."""
    path = os.environ.get("T24_SALES_STRIPE_WEBHOOK_SECRET_FILE")
    if not path and not os.environ.get("T24_SALES_STRIPE_WEBHOOK_SECRET"):
        path = DEFAULT_WEBHOOK_SECRET_FILE
    if path:
        try:
            if not os.path.isabs(path):
                return None
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                info = os.fstat(descriptor)
                if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                        or info.st_uid not in {0, os.geteuid()} or info.st_size > 4096):
                    return None
                value = os.read(descriptor, 4097).decode("ascii").strip()
            finally:
                os.close(descriptor)
        except (OSError, UnicodeError):
            return None
    else:
        value = os.environ.get("T24_SALES_STRIPE_WEBHOOK_SECRET", "").strip()
    return value if re.fullmatch(r"whsec_[A-Za-z0-9_=-]{12,250}", value) else None


def verify_signature(body, signature, *, now=None):
    secret = webhook_secret()
    if not secret:
        raise HTTPException(503, "销售 Stripe 回调尚未配置；仍可由老板凭真实凭证手工核款")
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(413, "回调内容超出限制")
    if not isinstance(signature, str) or len(signature) > 4096:
        raise HTTPException(400, "Stripe 签名无效")
    parts = [part.strip().split("=", 1) for part in signature.split(",")]
    timestamps = [value for part in parts if len(part) == 2 for key, value in [part] if key == "t"]
    signatures = [value for part in parts if len(part) == 2 for key, value in [part] if key == "v1"]
    if len(timestamps) != 1 or not re.fullmatch(r"\d{1,12}", timestamps[0]):
        raise HTTPException(400, "Stripe 签名无效")
    timestamp = int(timestamps[0])
    if abs((time.time() if now is None else now) - timestamp) > 300:
        raise HTTPException(400, "Stripe 签名已过期")
    expected = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    if not any(re.fullmatch(r"[a-f0-9]{64}", value) and hmac.compare_digest(expected, value) for value in signatures):
        raise HTTPException(400, "Stripe 签名无效")


async def _authorized_handoff(db, handoff_id, user):
    from services.sales_deal_handoffs import get_handoff
    await get_handoff(db, handoff_id, user)
    return await db.get(SalesDealHandoff, handoff_id, populate_existing=True)


async def can_request_payment(db, handoff, user):
    actor = await db.get(Employees, int(user.id), populate_existing=True)
    if not actor or actor.status not in {"active", "probation"} or str(actor.role) != str(user.role):
        return False
    if is_customer_owner(user):
        return True
    if str(actor.role) != "sales":
        return False
    lead = await db.get(SalesLeads, handoff.lead_id, populate_existing=True)
    # A collaboration invitation is never authority to send a new subscription.
    # Reassignment revokes the previous seller even if they originally registered.
    return bool(lead and lead.assigned_sales_id == actor.id)


async def duplicate_warnings(db, handoff):
    warnings = []
    active = await db.scalar(select(Subscriptions.id).where(
        Subscriptions.customer_id == handoff.customer_id,
        Subscriptions.id != (handoff.subscription_id or -1),
        Subscriptions.status.in_(["active", "trialing", "past_due"])).limit(1))
    if active:
        warnings.append("此客户已有在服或待处理订阅，请老板确认是否重复购买后再发送链接。")
    requests = (await db.scalars(select(SalesPaymentRequest.id).join(SalesDealHandoff,
        SalesDealHandoff.id == SalesPaymentRequest.handoff_id).where(
            SalesDealHandoff.customer_id == handoff.customer_id))).all()
    if requests:
        observations = (await db.scalars(select(SalesStripeObservation).where(
            SalesStripeObservation.request_id.in_(requests)))).all()
        if any(item.status in {"paid_observed", "processing"} for item in observations):
            warnings.append("此客户已收到支付成功或处理中记录，请先核对，不要重复订阅。")
        if any(item.subscription_id for item in observations):
            warnings.append("此客户已有关联的 Stripe 订阅记录；如需更换套餐，请由老板先核实原订阅。")
    return list(dict.fromkeys(warnings))


def request_data(row, warnings):
    item = row.link_snapshot
    return {"id": row.id, "url": item["url"] + "?" + urlencode({"client_reference_id": row.reference}),
        "reference": row.reference, "amount": item["amount_minor"] / 100,
        "currency": item["currency"], "billing_cycle": item["billing_cycle"],
        "cadence_label": CADENCES[item["billing_cycle"]], "tax_mode": "exclusive",
        "automatic_renewal": True, "status": "ready", "created_at": row.created_at,
        "duplicate_warnings": warnings, "duplicate_scope": DUPLICATE_SCOPE}


def handoff_link(handoff):
    link = approved_link(handoff.plan_snapshot)
    if not link or handoff.collection_method != "stripe_auto":
        return None
    if Decimal(str(handoff.amount)) * 100 != link["amount_minor"] or handoff.currency != link["currency"]:
        return None
    return link


async def get_request(db, handoff_id, user):
    handoff = await _authorized_handoff(db, handoff_id, user)
    allowed = await can_request_payment(db, handoff, user)
    valid = bool(handoff_link(handoff))
    can_create = allowed and valid and handoff.payment_status != "paid"
    reason = None if can_create else ("本次收款已核对，请勿再次订阅" if handoff.payment_status == "paid" else
        "该成交未绑定可核验的 Stripe 标准价格" if not valid else "仅老板或当前主要负责人可获取成交付款链接")
    row = await db.scalar(select(SalesPaymentRequest).where(SalesPaymentRequest.handoff_id == handoff.id)) if can_create else None
    return {"can_create": can_create, "read_only_reason": reason,
        "payment_request": request_data(row, await duplicate_warnings(db, handoff)) if row else None}


async def create_request(db, handoff_id, user):
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    handoff = await _authorized_handoff(db, handoff_id, user)
    if not await can_request_payment(db, handoff, user):
        raise HTTPException(403, "仅老板或当前主要负责人可获取成交付款链接；查看或协作邀请不包含收款操作")
    if handoff.payment_status == "paid":
        raise HTTPException(409, "本次收款已核对，请勿再次订阅")
    link = handoff_link(handoff)
    if not link:
        raise HTTPException(409, "冻结的套餐编号、价格、币种或周期不匹配已核验付款链接，请老板核对；不会猜测链接")
    row = await db.scalar(select(SalesPaymentRequest).where(SalesPaymentRequest.handoff_id == handoff.id))
    if row is None:
        row = SalesPaymentRequest(handoff_id=handoff.id, reference="t24_" + secrets.token_urlsafe(32),
            link_snapshot=link, created_by_id=int(user.id))
        db.add(row)
        await db.flush()
    return {"can_create": True, "read_only_reason": None,
        "payment_request": request_data(row, await duplicate_warnings(db, handoff))}


def _id(value, prefix):
    if isinstance(value, dict):
        value = value.get("id")
    return value if isinstance(value, str) and re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9_]{1,220}", value) else None


def _minor(value):
    return value if type(value) is int and 0 <= value <= 200000000 else None


def _instant(value):
    if type(value) is not int or not 0 < value < 253402300799:
        return None
    return datetime.fromtimestamp(value, timezone.utc)


def _text(value, limit):
    return value.strip() if isinstance(value, str) and len(value) <= limit and not any(ord(c) < 32 for c in value) else None


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


async def receive_event(db, body, signature):
    verify_signature(body, signature)
    try:
        event = json.loads(body)
    except (ValueError, UnicodeError):
        raise HTTPException(400, "回调不是有效 JSON")
    if not isinstance(event, dict):
        raise HTTPException(400, "回调格式无效")
    if not isinstance(event.get("type"), str) or event.get("type") not in EVENT_TYPES:
        return {"received": True}
    event_id = _id(event.get("id"), "evt_")
    at = _instant(event.get("created"))
    obj = event.get("data", {}).get("object") if isinstance(event.get("data"), dict) else None
    if not event_id or not at or not isinstance(obj, dict):
        raise HTTPException(400, "回调缺少必要记录信息")
    if event.get("livemode") is not True or obj.get("livemode") is not True:
        return {"received": True}
    if event.get("account") is not None and event.get("account") != STRIPE_ACCOUNT_ID:
        return {"received": True}
    session_id = _id(obj.get("id"), "cs_")
    reference = obj.get("client_reference_id")
    if not session_id or not isinstance(reference, str) or not re.fullmatch(r"t24_[A-Za-z0-9_-]{43}", reference):
        return {"received": True}
    await lock_sales_workflow(db)
    previous_event = await db.get(SalesStripeEvent, event_id)
    payload_digest = hashlib.sha256(body).hexdigest()
    if previous_event:
        # ID reuse with different signed payload is a conflict, never an update.
        if previous_event.payload_digest != payload_digest:
            raise HTTPException(409, "回调编号已存在")
        return {"received": True}
    request = await db.scalar(select(SalesPaymentRequest).where(SalesPaymentRequest.reference == reference))
    if not request:
        return {"received": True}
    link = request.link_snapshot
    if _id(obj.get("payment_link"), "plink_") != link["payment_link_id"] or obj.get("mode") != "subscription":
        return {"received": True}
    observation = await db.scalar(select(SalesStripeObservation).where(SalesStripeObservation.session_id == session_id))
    if observation and observation.request_id != request.id:
        raise HTTPException(409, "回调关联记录冲突")
    sub_id, invoice_id, intent_id = (_id(obj.get(name), prefix) for name, prefix in
        (("subscription", "sub_"), ("invoice", "in_"), ("payment_intent", "pi_")))
    clauses = [getattr(SalesStripeObservation, field) == value for field, value in
        (("subscription_id", sub_id), ("invoice_id", invoice_id), ("payment_intent_id", intent_id)) if value]
    issues = []
    if clauses and await db.scalar(select(SalesStripeObservation.id).where(
            SalesStripeObservation.request_id != request.id, or_(*clauses)).limit(1)):
        issues.append("cross_request_identity")
    service, gross = _minor(obj.get("amount_subtotal")), _minor(obj.get("amount_total"))
    details = obj.get("total_details") if isinstance(obj.get("total_details"), dict) else {}
    tax = _minor(details.get("amount_tax"))
    incomplete_terminal = event["type"] in {"checkout.session.async_payment_failed", "checkout.session.expired"}
    if service != link["amount_minor"] and (service is not None or not incomplete_terminal):
        issues.append("service_amount_mismatch")
    if obj.get("currency") != link["currency"].lower() and (obj.get("currency") is not None or not incomplete_terminal):
        issues.append("currency_mismatch")
    if (tax is None or gross is None or service is None) and not incomplete_terminal:
        issues.append("gross_tax_mismatch")
    elif tax is not None and gross is not None and service is not None and gross != service + tax:
        issues.append("gross_tax_mismatch")
    if details.get("amount_discount", 0) != 0 or details.get("amount_shipping", 0) != 0:
        issues.append("unexpected_discount_or_shipping")
    if not sub_id and event["type"] in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        issues.append("subscription_identity_missing")
    if event["type"] in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        new_status = "paid_observed" if obj.get("payment_status") == "paid" else "processing"
    elif event["type"] == "checkout.session.async_payment_failed":
        new_status = "failed"
    else:
        new_status = "expired"
    if issues:
        new_status = "needs_review"
    if observation is None:
        observation = SalesStripeObservation(request_id=request.id, session_id=session_id,
            status=new_status, match_issues=issues, latest_event_at=at)
        db.add(observation)
    elif observation.status == "paid_observed" and (new_status != "paid_observed" or at < _utc(observation.latest_event_at)):
        # A late pending/failed/expired callback cannot erase a paid observation.
        db.add(SalesStripeEvent(event_id=event_id, observation_id=observation.id, event_type=event["type"],
            payload_digest=payload_digest, stripe_created_at=at))
        await db.flush()
        return {"received": True}
    elif at < _utc(observation.latest_event_at):
        db.add(SalesStripeEvent(event_id=event_id, observation_id=observation.id, event_type=event["type"],
            payload_digest=payload_digest, stripe_created_at=at))
        await db.flush()
        return {"received": True}
    payer = obj.get("customer_details") if isinstance(obj.get("customer_details"), dict) else {}
    observation.subscription_id, observation.invoice_id, observation.payment_intent_id = sub_id, invoice_id, intent_id
    observation.service_minor, observation.tax_minor, observation.gross_minor = service, tax, gross
    observation.currency = _text(obj.get("currency"), 3).upper() if _text(obj.get("currency"), 3) else None
    observation.payer_business_name, observation.payer_name = _text(payer.get("business_name"), 255), _text(payer.get("name"), 255)
    observation.payer_email = _text(payer.get("email"), 320)
    observation.stripe_created_at = _instant(obj.get("created"))
    observation.status, observation.match_issues, observation.latest_event_at = new_status, issues, at
    if event["type"] == "checkout.session.completed":
        observation.checkout_completed_at = observation.checkout_completed_at or at
    if new_status == "paid_observed":
        observation.paid_at = observation.paid_at or at
    await db.flush()
    db.add(SalesStripeEvent(event_id=event_id, observation_id=observation.id, event_type=event["type"],
        payload_digest=payload_digest, stripe_created_at=at))
    await db.flush()
    return {"received": True}


def evidence_data(evidence):
    if not evidence:
        return None
    return {"id": evidence.id, "stripe_observation_id": evidence.observation_id,
        **{name + "_amount": getattr(evidence, name + "_minor") / 100 for name in ("service", "tax", "fee", "gross", "net")},
        "currency": evidence.currency, "payment_date": evidence.payment_date,
        "verified_by_name": evidence.verified_by_name, "created_at": evidence.created_at,
        "accounting_amount": evidence.service_minor / 100,
        "accounting_note": "原财务仅按服务费基价记账；税费、实际手续费和到账净额仅作独立核款凭据，未改财务公式。"}


async def observations(db, handoff_id, user):
    if not is_customer_owner(user):
        raise HTTPException(403, "付款凭据与付款人信息仅老板可核对")
    handoff = await _authorized_handoff(db, handoff_id, user)
    request = await db.scalar(select(SalesPaymentRequest).where(SalesPaymentRequest.handoff_id == handoff.id))
    rows = (await db.scalars(select(SalesStripeObservation).where(SalesStripeObservation.request_id == request.id)
        .order_by(SalesStripeObservation.id.desc()))).all() if request else []
    evidence = await db.scalar(select(SalesReceiptEvidence).where(SalesReceiptEvidence.handoff_id == handoff.id))
    return {"items": [{"id": item.id, "status": item.status, "match_issues": item.match_issues,
        "session_id": item.session_id, "subscription_id": item.subscription_id, "invoice_id": item.invoice_id,
        "payment_intent_id": item.payment_intent_id, "currency": item.currency,
        "service_amount": item.service_minor / 100 if item.service_minor is not None else None,
        "tax_amount": item.tax_minor / 100 if item.tax_minor is not None else None,
        "gross_amount": item.gross_minor / 100 if item.gross_minor is not None else None,
        "payer_business_name": item.payer_business_name, "payer_name": item.payer_name, "payer_email": item.payer_email,
        "checkout_completed_at": item.checkout_completed_at, "paid_at": item.paid_at,
        "received_at": item.received_at} for item in rows], "receipt_evidence": evidence_data(evidence),
        "duplicate_warnings": await duplicate_warnings(db, handoff), "duplicate_scope": DUPLICATE_SCOPE,
        "identity_note": "关联编号仅帮助匹配成交单，请核验付款商家与邮箱；Stripe 回调不自动确认客户归属或记账。",
        "date_note": "Checkout 与扣款日期不等于服务开始日；服务区间仍以成交登记快照为准。"}


def _money_minor(value):
    amount = Decimal(str(value))
    return int(amount * 100)


async def prepare_receipt_evidence(db, handoff, payload, user):
    """Validate before the existing ledger write; persist in the same transaction."""
    names = ("service_amount", "tax_amount", "fee_amount", "gross_amount", "net_amount")
    values = [getattr(payload, name, None) for name in names]
    observation_id = getattr(payload, "stripe_observation_id", None)
    provided = any(value is not None for value in values)
    if not provided and observation_id is None:
        return None
    if not all(value is not None for value in values) or payload.payment_method != "stripe":
        raise HTTPException(400, "Stripe 核款应完整填写服务费、税、手续费、客户实付和到账净额")
    amounts = dict(zip(names, (_money_minor(value) for value in values)))
    service, tax, fee, gross, net = (amounts[name] for name in names)
    if service != _money_minor(handoff.amount) or service != _money_minor(payload.amount_received):
        raise HTTPException(400, "服务费基价必须等于成交金额，税费不能计入公司服务收入")
    if gross != service + tax or net != gross - fee or fee > gross:
        raise HTTPException(400, "金额不平：客户实付应等于服务费加税，到账净额应等于实付减手续费")
    request = await db.scalar(select(SalesPaymentRequest).where(SalesPaymentRequest.handoff_id == handoff.id))
    observation = await db.get(SalesStripeObservation, observation_id) if observation_id else None
    if observation_id:
        if not observation or not request or observation.request_id != request.id:
            raise HTTPException(400, "付款观察不属于本成交单")
        if observation.status != "paid_observed" or observation.match_issues:
            raise HTTPException(409, "该付款记录尚未成功或存在关联异常，请先核对；不会标记收款")
        if (observation.service_minor, observation.tax_minor, observation.gross_minor, observation.currency) != (service, tax, gross, payload.currency):
            raise HTTPException(400, "填写金额与所选 Stripe 付款记录不符")
        # One subscription/invoice must never verify two different handoffs.
        identity_clauses = [getattr(SalesStripeObservation, field) == getattr(observation, field) for field in
            ("subscription_id", "invoice_id", "payment_intent_id") if getattr(observation, field)]
        if identity_clauses and await db.scalar(select(SalesReceiptEvidence.id).join(
                SalesStripeObservation, SalesStripeObservation.id == SalesReceiptEvidence.observation_id).where(
                    SalesReceiptEvidence.handoff_id != handoff.id, or_(*identity_clauses)).limit(1)):
            raise HTTPException(409, "该 Stripe 订阅或付款已关联其他已核款成交，请先核对，避免重复记账")
    reference_digest = hashlib.sha256((payload.currency + ":" + payload.transaction_reference.strip().casefold()).encode()).hexdigest()
    duplicate = await db.scalar(select(SalesReceiptEvidence.id).where(
        SalesReceiptEvidence.transaction_reference_digest == reference_digest,
        SalesReceiptEvidence.handoff_id != handoff.id))
    if duplicate:
        raise HTTPException(409, "该付款凭证已用于其他成交核款，请先核对，避免重复记账")
    row = SalesReceiptEvidence(handoff_id=handoff.id, observation_id=observation_id,
        transaction_reference_digest=reference_digest, service_minor=service, tax_minor=tax,
        fee_minor=fee, gross_minor=gross, net_minor=net, currency=payload.currency,
        payment_date=payload.payment_date.isoformat(), verified_by_id=int(user.id), verified_by_name=user.name)
    db.add(row)
    await db.flush()
    return row
