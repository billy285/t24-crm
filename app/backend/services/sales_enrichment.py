"""Atomic sales-only enrichment. Caller owns workflow lock, scope and commit."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customers
from models.management_decisions import BusinessLine, ProductCatalog
from models.sales_leads import SalesLeads
from models.sales_lead_enrichments import SalesLeadEnrichment, SalesLeadEnrichmentAudit
from schemas.sales_enrichment import SalesEnrichmentUpdate
from services.phone_numbers import parse_phone_number, phone_match_key

BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")

CORE_FIELDS = ("business_name", "industry", "city", "state", "country", "address", "website")
PROFILE_FIELDS = ("contacts", "preferred_contact_id", "interest_product_ids", "need_summary", "best_contact_time", "verification")


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value.astimezone(timezone.utc) if value else None


def enrichment_read_only_reason(lead):
    if lead.converted_customer_id or lead.converted_at or lead.status == "converted":
        return "线索已转为客户，销售补全已关闭"
    if lead.is_blacklisted or lead.do_not_contact:
        return "商家已禁止联系，销售补全已关闭"
    return None


def ensure_enrichment_editable(lead):
    reason = enrichment_read_only_reason(lead)
    if reason:
        raise HTTPException(status_code=409, detail=reason)


async def enrichment_catalog(db: AsyncSession):
    today = datetime.now(BUSINESS_TIMEZONE).date()
    query = select(ProductCatalog.id, ProductCatalog.name).join(BusinessLine).where(
        ProductCatalog.is_active.is_(True), BusinessLine.is_active.is_(True),
        or_(ProductCatalog.effective_from.is_(None), ProductCatalog.effective_from <= today),
        or_(ProductCatalog.effective_to.is_(None), ProductCatalog.effective_to >= today),
    ).order_by(ProductCatalog.id)
    return [{"id": row.id, "name": row.name} for row in (await db.execute(query)).all()]


async def _profile(db, lead_id):
    return (await db.execute(select(SalesLeadEnrichment).where(SalesLeadEnrichment.lead_id == lead_id)
                             .execution_options(populate_existing=True))).scalar_one_or_none()


def _business_snapshot(lead, profile):
    initial_contacts = [{"id": f"legacy-{lead.id}", "name": lead.contact_name, "role": None,
        "phone": None, "email": None, "wechat": None, "verification": "pending"}] if lead.contact_name else []
    return {**{key: getattr(lead, key) for key in CORE_FIELDS}, "store_phone": lead.phone,
        "contacts": list(profile.contacts or []) if profile else initial_contacts,
        "preferred_contact_id": profile.preferred_contact_id if profile else (initial_contacts[0]["id"] if initial_contacts else None),
        "interest_product_ids": list(profile.interest_product_ids or []) if profile else [],
        "need_summary": profile.need_summary if profile else None,
        "best_contact_time": profile.best_contact_time if profile else None,
        "verification": profile.verification if profile else "pending"}


def _phone(raw, country, verification):
    if not raw:
        return None, None
    parsed = parse_phone_number(raw, country)
    if parsed.is_valid and not parsed.extension:
        return parsed.e164, None
    if verification == "confirmed":
        raise HTTPException(status_code=422, detail="已确认的电话必须是有效的单一号码；分机请先保留待核实")
    return raw, "有电话号码尚未核实，补齐国家码或修正后才能拨打"


async def _duplicate_keys(db, lead_id, snapshot):
    keys = {phone_match_key(snapshot["store_phone"], snapshot["country"])}
    keys.update(phone_match_key(item.get("phone"), snapshot["country"]) for item in snapshot["contacts"])
    keys.discard(None)
    if not keys:
        return set()
    existing = set()
    for phone, country in (await db.execute(select(SalesLeads.phone, SalesLeads.country).where(SalesLeads.id != lead_id))).all():
        if (key := phone_match_key(phone, country)) in keys:
            existing.add(key)
    for contacts, country in (await db.execute(select(SalesLeadEnrichment.contacts, SalesLeads.country)
        .join(SalesLeads, SalesLeads.id == SalesLeadEnrichment.lead_id).where(SalesLeadEnrichment.lead_id != lead_id))).all():
        for contact in contacts or []:
            if isinstance(contact, dict) and (key := phone_match_key(contact.get("phone"), country)) in keys:
                existing.add(key)
    # Only the collision boolean leaves this service; no customer identity,
    # ownership, name, source, financial value or record link is returned.
    for phone, country in (await db.execute(select(Customers.phone, Customers.country))).all():
        if (key := phone_match_key(phone, country)) in keys:
            existing.add(key)
    return existing


async def _warnings(db, lead_id, snapshot):
    warnings = []
    for raw in [snapshot["store_phone"], *[c.get("phone") for c in snapshot["contacts"]]]:
        if raw:
            parsed = parse_phone_number(raw, snapshot["country"])
            if not parsed.is_valid or parsed.extension:
                warnings.append("有电话号码尚未核实，补齐国家码或修正后才能拨打")
                break
    valid_products = {item["id"] for item in await enrichment_catalog(db)}
    if not set(snapshot["interest_product_ids"]).issubset(valid_products):
        warnings.append("有意向产品已停用，请重新选择后保存")
    duplicates = await _duplicate_keys(db, lead_id, snapshot)
    if duplicates:
        warnings.append("联系方式可能存在重复，请先核实；系统不会自动合并或显示其他记录")
    return warnings


async def get_enrichment(db: AsyncSession, lead):
    profile = await _profile(db, lead.id)
    snapshot = _business_snapshot(lead, profile)
    reason = enrichment_read_only_reason(lead)
    return {"lead_id": lead.id, "revision": profile.revision if profile else 0,
        "lead_updated_at": _utc(lead.updated_at).isoformat(), **snapshot,
        "can_edit": reason is None, "read_only_reason": reason,
        "updated_by_name": profile.updated_by_name if profile else None,
        "updated_at": profile.updated_at if profile else None,
        "warnings": await _warnings(db, lead.id, snapshot)}


async def apply_enrichment(db: AsyncSession, lead, payload: SalesEnrichmentUpdate, user):
    ensure_enrichment_editable(lead)
    profile = await _profile(db, lead.id)
    revision = profile.revision if profile else 0
    if payload.expected_revision != revision or _utc(payload.expected_lead_updated_at) != _utc(lead.updated_at):
        raise HTTPException(status_code=409, detail="资料或线索已更新，本次没有覆盖；请刷新后核对再保存")
    valid_products = {item["id"] for item in await enrichment_catalog(db)}
    if not set(payload.interest_product_ids).issubset(valid_products):
        raise HTTPException(status_code=422, detail="意向产品已停用或不存在，请重新选择")
    before = _business_snapshot(lead, profile)
    after = payload.model_dump(exclude={"expected_revision", "expected_lead_updated_at", "source"})
    after["store_phone"], _ = _phone(after["store_phone"], after["country"], after["verification"])
    for contact in after["contacts"]:
        contact["phone"], _ = _phone(contact["phone"], after["country"], contact["verification"])
    duplicates = await _duplicate_keys(db, lead.id, after)
    if duplicates:
        after["verification"] = "pending"
        for contact in after["contacts"]:
            if phone_match_key(contact["phone"], after["country"]) in duplicates:
                contact["verification"] = "pending"
    now = datetime.now(timezone.utc)
    for key in CORE_FIELDS:
        setattr(lead, key, after[key])
    lead.phone = after["store_phone"]
    if after["preferred_contact_id"]:
        preferred = next(item for item in after["contacts"] if item["id"] == after["preferred_contact_id"])
        if preferred["name"]:
            lead.contact_name = preferred["name"]
    lead.updated_at = now
    if profile is None:
        profile = SalesLeadEnrichment(lead_id=lead.id)
        db.add(profile)
    profile.revision = revision + 1
    for key in PROFILE_FIELDS:
        setattr(profile, key, after[key])
    profile.updated_by_id, profile.updated_by_name, profile.updated_at = int(user.id), user.name, now
    db.add(SalesLeadEnrichmentAudit(lead_id=lead.id, revision=profile.revision, source=payload.source,
        changed_fields=[key for key in after if after[key] != before.get(key)], before=before, after=after,
        actor_id=int(user.id), actor_name=user.name, created_at=now))
    await db.flush()


async def saved_dial_phone(db, lead, requested_phone=None):
    """Only a saved, unambiguous real number can be launched by the dial button."""
    profile = await _profile(db, lead.id)
    allowed = [lead.phone, *[item.get("phone") for item in (profile.contacts or [])]] if profile else [lead.phone]
    parsed = parse_phone_number(requested_phone or lead.phone, lead.country)
    if not parsed.is_valid or parsed.extension:
        raise HTTPException(status_code=422, detail="请先保存并核实一个有效电话号码，再拨打")
    valid_saved = {result.e164 for raw in allowed if raw for result in [parse_phone_number(raw, lead.country)]
                   if result.is_valid and not result.extension}
    if parsed.e164 not in valid_saved:
        raise HTTPException(status_code=409, detail="此号码尚未保存，请先保存资料后再拨打")
    return parsed.e164


async def enrichment_summaries(db, leads):
    """Batch-only summaries for the caller's already authorized queue."""
    if not leads:
        return {}
    profiles = {row.lead_id: row for row in (await db.execute(select(SalesLeadEnrichment)
        .where(SalesLeadEnrichment.lead_id.in_([lead.id for lead in leads])))).scalars()}
    product_ids = {pid for profile in profiles.values() for pid in profile.interest_product_ids or []}
    names = dict((await db.execute(select(ProductCatalog.id, ProductCatalog.name)
                                   .where(ProductCatalog.id.in_(product_ids)))).all()) if product_ids else {}
    summaries = {}
    for lead in leads:
        profile = profiles.get(lead.id)
        snapshot = _business_snapshot(lead, profile)
        phones = [snapshot["store_phone"], *[item.get("phone") for item in snapshot["contacts"]]]
        invalid = any(not parse_phone_number(raw, lead.country).is_valid or parse_phone_number(raw, lead.country).extension
                      for raw in phones if raw)
        summaries[lead.id] = {"has_contact": bool(snapshot["contacts"]),
            "needs_review": not profile or snapshot["verification"] != "confirmed" or bool(invalid)
                or any(item.get("verification") != "confirmed" for item in snapshot["contacts"]),
            "has_interest": bool(snapshot["interest_product_ids"]),
            "interest_product_names": [names[pid] for pid in snapshot["interest_product_ids"] if pid in names],
            "revision": profile.revision if profile else 0}
    return summaries
