"""Explainable local-time queue ordering; never changes contact permissions."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from models.sales_intelligence import SalesLeadProfiles, SalesOperatingSettings
from services.sales_intelligence import default_config, unpack
from services.sales_timezones import resolve_contact_timezone
from services.merchant_identity import has_concrete_name_and_address


def aware(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def queue_context(db, leads, target_date):
    ids = [lead.id for lead in leads]
    profiles = (await db.scalars(select(SalesLeadProfiles).where(SalesLeadProfiles.lead_id.in_(ids)))).all() if ids else []
    settings = (await db.scalars(select(SalesOperatingSettings).where(
        SalesOperatingSettings.effective_month <= target_date.strftime('%Y-%m')
    ).order_by(SalesOperatingSettings.effective_month.desc()).limit(1))).first()
    config = {**default_config(), **(unpack(settings.payload_json).get('config', {}) if settings else {})}
    start, end = config.get('default_contact_start', 10), config.get('default_contact_end', 18)
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= 24:
        start, end = 10, 18
    return {row.lead_id: unpack(row.payload_json) for row in profiles}, start, end


def contact_queue_context(lead, *, now=None, profile=None, start=10, end=18):
    now = aware(now or datetime.now(timezone.utc))
    profile = profile or {}
    resolved = resolve_contact_timezone(country=lead.country, state=lead.state,
        city=lead.city, address=lead.address, profile_timezone=profile.get('timezone'))
    local = now.astimezone(ZoneInfo(resolved['timezone'])) if resolved['timezone'] else None
    due = aware(lead.next_follow_up_at)
    overdue = bool(due and due <= now)
    in_window = bool(local and start <= local.hour < end)
    label = '到期回访优先' if overdue else '建议联系时段内' if in_window else '时区待确认' if not local else '等待当地联系时段'
    return {**resolved, 'local_time': local.isoformat() if local else None,
        'in_contact_window': in_window if local else None,
        'contact_start': start, 'contact_end': end, 'due_follow_up': overdue,
        'queue_reason': label}


def queue_sort_key(lead, context, *, completed=False):
    # Due promises stay ahead of new calls, including an explicitly agreed
    # after-hours callback. Unknown geography remains visible, without a fake clock.
    due = aware(lead.next_follow_up_at)
    priority = 0 if context['due_follow_up'] else 1 if context['in_contact_window'] else 2 if context['in_contact_window'] is False else 3
    quality = sum(bool(getattr(lead, name, None)) for name in ('contact_name', 'city', 'website')) + int(has_concrete_name_and_address(lead))
    return (1 if completed else 0, priority,
        due if context['due_follow_up'] else datetime.max.replace(tzinfo=timezone.utc),
        0 if lead.status in {'follow_up', 'interested', 'appointment'} else 1,
        -quality, lead.id)
