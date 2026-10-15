"""Fail-closed, sales-only contact guard. Caller owns scope, lock and commit.

Only a generic protection message leaves these checks. Matching phone numbers
never disclose another prospect, employee or customer identity.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select

from models.sales_contact_protection import SalesContactProtectionAudit, SalesPhoneSuppression
from models.sales_lead_enrichments import SalesDialAttempt, SalesLeadEnrichment, SalesLeadEnrichmentAudit
from models.sales_leads import SalesLeads
from models.sales_dossiers import SalesDossierHandoff
from services.phone_numbers import phone_match_key

PROTECTION_NOTICE = "该联系方式受联系保护，请由老板核实；本次没有拨打或记录联系"


def lead_is_blocked(lead):
    return bool(lead.do_not_contact or lead.is_blacklisted or lead.status == "blocked")


def snapshot_phone_keys(snapshot, country=None):
    snapshot = snapshot or {}
    country = snapshot.get("country") or country
    raw = [snapshot.get("store_phone"), snapshot.get("phone")]
    raw += [contact.get("phone") for contact in snapshot.get("contacts", []) if isinstance(contact, dict)]
    return {key for value in raw if (key := phone_match_key(value, country))}


async def lead_phone_keys(db, lead, *, historical=False):
    keys = {key for key in [phone_match_key(lead.phone, lead.country)] if key}
    profile = await db.get(SalesLeadEnrichment, lead.id)
    if profile:
        keys |= snapshot_phone_keys({"contacts": profile.contacts}, lead.country)
    if historical:
        audits = (await db.execute(select(SalesLeadEnrichmentAudit).where(
            SalesLeadEnrichmentAudit.lead_id == lead.id))).scalars()
        for row in audits:
            keys |= snapshot_phone_keys(row.before, lead.country)
            keys |= snapshot_phone_keys(row.after, lead.country)
        attempts = (await db.execute(select(SalesDialAttempt.dial_phone).where(
            SalesDialAttempt.lead_id == lead.id))).scalars()
        keys |= {key for raw in attempts if (key := phone_match_key(raw, lead.country))}
    return keys


async def blocked_phone_keys(db, keys):
    """Includes legacy protected leads until their durable ledger is seeded."""
    keys = set(keys)
    if not keys:
        return set()
    ledger = {row.phone_key: row.blocked for row in (await db.execute(
        select(SalesPhoneSuppression).where(SalesPhoneSuppression.phone_key.in_(keys)))).scalars()}
    blocked = {key for key, value in ledger.items() if value}
    missing = keys - set(ledger)
    if missing:
        protected = (await db.execute(select(SalesLeads).where(or_(
            SalesLeads.do_not_contact.is_(True), SalesLeads.is_blacklisted.is_(True),
            SalesLeads.status == "blocked")))).scalars()
        for lead in protected:
            blocked |= missing & await lead_phone_keys(db, lead, historical=True)
    return blocked


async def ensure_phone_contact_allowed(db, phone, country=None):
    key = phone_match_key(phone, country)
    if key and await blocked_phone_keys(db, {key}):
        raise HTTPException(status_code=409, detail=PROTECTION_NOTICE)


async def contact_protection_summary(db, lead):
    """Read-only presentation, never revealing the source of a phone match."""
    cooldown = lead.cooldown_until
    if cooldown and cooldown.tzinfo is None:
        cooldown = cooldown.replace(tzinfo=timezone.utc)
    keys = await lead_phone_keys(db, lead)
    blocked = await blocked_phone_keys(db, keys)
    reason = PROTECTION_NOTICE if lead_is_blocked(lead) or blocked else None
    if not reason and cooldown and cooldown > datetime.now(timezone.utc):
        reason = "仍在联系冷却期，请到期后按原计划联系"
    if not reason and await has_pending_handoff(db, lead):
        reason = "请先确认接收交接摘要，再继续联系商家"
    return {"can_contact": reason is None, "reason": reason, "cooldown_until": cooldown,
        "protected_phones": sorted(blocked)}


async def has_pending_handoff(db, lead):
    return (await db.execute(select(SalesDossierHandoff.id).where(
        SalesDossierHandoff.lead_id == lead.id,
        SalesDossierHandoff.to_sales_id == lead.assigned_sales_id,
        SalesDossierHandoff.status == "pending").limit(1))).scalar_one_or_none() is not None


async def ensure_lead_contact_allowed(db, lead, phone=None, *, check_schedule=True):
    if lead_is_blocked(lead):
        raise HTTPException(status_code=409, detail=PROTECTION_NOTICE)
    keys = {phone_match_key(phone, lead.country)} if phone else await lead_phone_keys(db, lead)
    keys.discard(None)
    if await blocked_phone_keys(db, keys):
        raise HTTPException(status_code=409, detail=PROTECTION_NOTICE)
    now = datetime.now(timezone.utc)
    cooldown = lead.cooldown_until
    if cooldown and cooldown.tzinfo is None:
        cooldown = cooldown.replace(tzinfo=timezone.utc)
    if check_schedule and cooldown and cooldown > now:
        raise HTTPException(status_code=409, detail="该商家仍在联系冷却期，请到期后按原计划联系")
    if check_schedule and await has_pending_handoff(db, lead):
        raise HTTPException(status_code=409, detail="请先确认接收交接摘要，再继续联系商家")


async def persist_lead_suppression(db, lead, user=None, *, reason=None, extra_phones=(), preserve_releases=False):
    """Durable rows deliberately have no FK to mutable/deletable lead data."""
    keys = await lead_phone_keys(db, lead, historical=True)
    keys |= {key for raw in extra_phones if (key := phone_match_key(raw, lead.country))}
    now = datetime.now(timezone.utc)
    actor_id = int(user.id) if user is not None else None
    actor_name = user.name if user is not None else "系统联系保护"
    reason = (reason or lead.do_not_contact_reason or "商家已被标记禁止联系").strip()
    for key in keys:
        row = await db.get(SalesPhoneSuppression, key)
        if row is not None and (row.blocked or preserve_releases):
            continue
        if row is None:
            row = SalesPhoneSuppression(phone_key=key)
            db.add(row)
        row.blocked, row.reason, row.source_lead_id = True, reason, lead.id
        row.actor_id, row.actor_name, row.updated_at = actor_id, actor_name, now
        db.add(SalesContactProtectionAudit(phone_key=key, lead_id=lead.id, action="blocked",
            reason=reason, actor_id=actor_id, actor_name=actor_name, created_at=now))
    await db.flush()


async def release_phone_suppression(db, lead, phone, user, reason, *, resume_lead=False):
    key = phone_match_key(phone, lead.country)
    if not key or key not in await lead_phone_keys(db, lead, historical=True):
        raise HTTPException(status_code=422, detail="请选择此商家已保存的联系方式")
    now = datetime.now(timezone.utc)
    row = await db.get(SalesPhoneSuppression, key)
    if row is None:
        row = SalesPhoneSuppression(phone_key=key)
        db.add(row)
    row.blocked, row.reason, row.source_lead_id = False, reason, lead.id
    row.actor_id, row.actor_name, row.updated_at = int(user.id), user.name, now
    await db.flush()
    if resume_lead:
        if await blocked_phone_keys(db, await lead_phone_keys(db, lead)):
            raise HTTPException(status_code=409, detail="此商家仍有受保护联系方式，请逐一核实后再恢复联系")
        lead.do_not_contact = False
        lead.is_blacklisted = False
        lead.do_not_contact_reason = None
        if lead.status == "blocked":
            lead.status = "contacted"
        lead.automation_state = "assigned" if lead.assigned_sales_id else "eligible"
        lead.updated_at = now
    db.add(SalesContactProtectionAudit(phone_key=key, lead_id=lead.id,
        action="released_and_resumed" if resume_lead else "released", reason=reason,
        actor_id=int(user.id), actor_name=user.name, created_at=now))
    return key
