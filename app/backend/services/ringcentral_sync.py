from datetime import datetime, timedelta, timezone
import re
from typing import Any

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from models.employees import Employees
from models.ringcentral_call_records import RingCentralCallRecords
from models.ringcentral_connections import RingCentralConnections
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_lead_enrichments import SalesDialAttempt
from models.sales_leads import SalesLeads
from services.phone_numbers import phone_match_key


CONNECTED_CODES = {"answered", "connected", "established"}
TERMINAL_CODES = {"completed", "disconnected", "finished", "gone", "hangup", "terminated"}
CALL_TASK_MATCH_WINDOW = timedelta(hours=12)


def normalize_phone(value: Any, country: str | None = None) -> str:
    return phone_match_key(str(value or ""), country) or ""


def _parse_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _party_phone(value: Any) -> str | None:
    if isinstance(value, dict):
        return str(value.get("phoneNumber") or "").strip() or None
    return str(value or "").strip() or None


def _event_party(body: dict[str, Any], extension_id: str | None = None) -> dict[str, Any]:
    parties = list(body.get("parties") or [])
    if extension_id:
        for party in parties:
            candidates = {
                str(party.get("extensionId") or ""),
                str((party.get("extension") or {}).get("id") or ""),
            }
            if extension_id in candidates:
                return party
    return parties[0] if parties else body


def _status_code(party: dict[str, Any], body: dict[str, Any]) -> str:
    status = party.get("status") or body.get("status") or ""
    if isinstance(status, dict):
        status = status.get("code") or status.get("description") or ""
    return str(status).strip()


def _recording_uri(record: dict[str, Any]) -> str | None:
    recording = record.get("recording") or {}
    return str(recording.get("contentUri") or recording.get("uri") or "").strip() or None


async def _connection_for_event(db: AsyncSession, payload: dict[str, Any]) -> RingCentralConnections | None:
    body = payload.get("body") or {}
    # Account+extension are the identity. A short extension number or a first
    # matching row is insufficient in a multi-account sales team.
    event_path = str(payload.get("event") or "")
    account_match = re.search(r"/account/([^/?]+)", event_path)
    extension_match = re.search(r"/extension/([^/?]+)", event_path)
    accounts = {str(value).strip() for value in [payload.get("accountId"), body.get("accountId"),
                account_match.group(1) if account_match else None] if value and str(value).strip() != "~"}
    if len(accounts) > 1:
        return None
    account_id = next(iter(accounts), None)
    path_extension = extension_match.group(1) if extension_match and extension_match.group(1) != "~" else None
    owner_id = str(payload.get("ownerId") or body.get("ownerId") or "").strip()
    extension_ids = {path_extension} if path_extension else {owner_id}
    if not path_extension:
        for party in body.get("parties") or []:
            extension_ids.add(str(party.get("extensionId") or "").strip())
            extension_ids.add(str((party.get("extension") or {}).get("id") or "").strip())
    extension_ids.discard("")
    extension_ids.discard(None)
    if not extension_ids:
        return None
    query = select(RingCentralConnections).where(
        RingCentralConnections.ringcentral_extension_id.in_(extension_ids),
        RingCentralConnections.is_active.is_(True))
    if account_id:
        query = query.where(RingCentralConnections.ringcentral_account_id == account_id)
    candidates = (await db.execute(query)).scalars().all()
    # Historical inactive authorizations do not own current events. Ambiguous
    # simultaneous active bindings still fail closed.
    if len(candidates) != 1 or not candidates[0].is_active:
        return None
    return candidates[0]


async def _match_lead_and_task(
    db: AsyncSession,
    employee_id: int,
    remote_phone: str | None,
    call_started_at: datetime | None,
) -> tuple[SalesLeads | None, SalesDailyDialTasks | None]:
    normalized = normalize_phone(remote_phone)
    if not normalized:
        return None, None

    # A dial snapshot records who actually called which number. It remains
    # authoritative after a contact number changes or a lead is reassigned.
    # Do not pick the newest of multiple plausible tasks: provider data does
    # not prove which one was dialled in that case.
    if call_started_at:
        earliest_dial = _utc(call_started_at) - CALL_TASK_MATCH_WINDOW
        latest_dial = _utc(call_started_at) + timedelta(minutes=5)
        attempt_rows = (
            await db.execute(
                select(SalesDialAttempt, SalesDailyDialTasks, SalesLeads)
                .join(SalesDailyDialTasks, SalesDialAttempt.task_id == SalesDailyDialTasks.id)
                .join(SalesLeads, SalesDialAttempt.lead_id == SalesLeads.id)
                .where(
                    SalesDialAttempt.sales_employee_id == employee_id,
                    SalesDialAttempt.started_at >= earliest_dial,
                    SalesDialAttempt.started_at <= latest_dial,
                )
            )
        ).all()
        attempt_contexts = {
            (lead.id, task.id): (lead, task)
            for attempt, task, lead in attempt_rows
            if task.sales_employee_id == employee_id
            and task.lead_id == lead.id
            and normalize_phone(attempt.dial_phone) == normalized
            and _within_call_window(attempt.started_at, call_started_at)
        }
        # Repeated calls within one task share a context, but two customers
        # with the same phone cannot be distinguished safely. Immutable
        # attempts keep an earlier store call after a later mobile call.
        if attempt_contexts:
            return next(iter(attempt_contexts.values())) if len(attempt_contexts) == 1 else (None, None)
        dial_rows = (
            await db.execute(
                select(SalesDailyDialTasks, SalesLeads)
                .join(SalesLeads, SalesDailyDialTasks.lead_id == SalesLeads.id)
                .where(
                    SalesDailyDialTasks.sales_employee_id == employee_id,
                    SalesDailyDialTasks.dial_started_at >= earliest_dial,
                    SalesDailyDialTasks.dial_started_at <= latest_dial,
                    ~select(SalesDialAttempt.id).where(
                        SalesDialAttempt.task_id == SalesDailyDialTasks.id
                    ).exists(),
                )
            )
        ).all()
        snapshot_matches = [
            (lead, task) for task, lead in dial_rows
            if task.dial_phone
            and normalize_phone(task.dial_phone) == normalized
            and _within_call_window(task.dial_started_at, call_started_at)
        ]
        if snapshot_matches:
            return snapshot_matches[0] if len(snapshot_matches) == 1 else (None, None)

    leads = (
        await db.execute(select(SalesLeads).where(SalesLeads.assigned_sales_id == employee_id))
    ).scalars().all()
    matches = [candidate for candidate in leads if normalize_phone(candidate.phone, candidate.country) == normalized]
    # Shared business numbers must not attach a provider call to an arbitrary lead.
    if len(matches) != 1:
        return None, None
    lead = matches[0]
    tasks = (
        await db.execute(
            select(SalesDailyDialTasks)
            .where(
                SalesDailyDialTasks.sales_employee_id == employee_id,
                SalesDailyDialTasks.lead_id == lead.id,
                SalesDailyDialTasks.dial_started_at.is_not(None),
                ~select(SalesDialAttempt.id).where(
                    SalesDialAttempt.task_id == SalesDailyDialTasks.id
                ).exists(),
            )
            .order_by(SalesDailyDialTasks.dial_started_at.desc(), SalesDailyDialTasks.id.desc())
        )
    ).scalars().all()
    # Only pre-migration tasks can fall back to the current lead phone. A
    # populated snapshot for a different number must never be rewritten by it.
    legacy_matches = [
        candidate for candidate in tasks
        if not candidate.dial_phone
        and call_started_at
        and _within_call_window(candidate.dial_started_at, call_started_at)
    ]
    if len(legacy_matches) > 1:
        return None, None
    return lead, legacy_matches[0] if legacy_matches else None


def _utc(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _within_call_window(dial_time: datetime | None, call_time: datetime) -> bool:
    if not dial_time:
        return False
    delta = _utc(call_time) - _utc(dial_time)
    return -timedelta(minutes=5) <= delta <= CALL_TASK_MATCH_WINDOW


async def _linked_activity(
    db: AsyncSession,
    employee_id: int,
    lead_id: int | None,
    task: SalesDailyDialTasks | None,
    *,
    remote_phone: str | None = None,
    call_started_at: datetime | None = None,
) -> SalesCallActivities | None:
    if task:
        if task.sales_employee_id != employee_id or task.lead_id != lead_id:
            return None
        attempts = (
            await db.execute(
                select(SalesDialAttempt).where(
                    SalesDialAttempt.task_id == task.id,
                    SalesDialAttempt.sales_employee_id == employee_id,
                    SalesDialAttempt.lead_id == lead_id,
                )
            )
        ).scalars().all()
        if attempts:
            # A completed daily task can be called again for a follow-up.
            # Its completed_activity_id still points to the original result,
            # so new calls must bind through their immutable attempt instead.
            # Until that attempt has a result, leave the provider row unlinked.
            normalized = normalize_phone(remote_phone)
            candidates = [attempt for attempt in attempts
                          if normalized and call_started_at
                          and normalize_phone(attempt.dial_phone) == normalized
                          and _within_call_window(attempt.started_at, call_started_at)]
            if len(candidates) != 1:
                return None
            activity = (
                await db.execute(
                    select(SalesCallActivities).where(
                        SalesCallActivities.dial_attempt_id == candidates[0].id,
                        SalesCallActivities.sales_employee_id == employee_id,
                        SalesCallActivities.lead_id == lead_id,
                    )
                )
            ).scalars().one_or_none()
            return activity if activity and normalize_phone(activity.dial_phone) == normalized else None
        if task.completed_activity_id:
            activity = await db.get(SalesCallActivities, task.completed_activity_id)
            if activity and activity.sales_employee_id == employee_id and activity.lead_id == lead_id:
                if not activity.dial_phone or normalize_phone(activity.dial_phone) == normalize_phone(remote_phone):
                    return activity
            return None
    normalized = normalize_phone(remote_phone)
    if not lead_id or not normalized or not call_started_at:
        return None
    activities = (
        await db.execute(
            select(SalesCallActivities)
            .where(
                SalesCallActivities.sales_employee_id == employee_id,
                SalesCallActivities.lead_id == lead_id,
            )
            .order_by(SalesCallActivities.called_at.desc(), SalesCallActivities.id.desc())
        )
    ).scalars().all()
    # A manual follow-up can exist without a daily task, but only a unique
    # actual-number snapshot saved around this call is enough to link it.
    # In particular, a stale provider call must not overwrite the latest note.
    matches = [
        activity for activity in activities
        if activity.dial_attempt_id is None
        and activity.dial_phone
        and normalize_phone(activity.dial_phone) == normalized
        and _within_call_window(call_started_at, activity.called_at)
    ]
    return matches[0] if len(matches) == 1 else None


def _provider_key(*values: Any) -> str:
    return next((str(value) for value in values if value), "")


async def _new_call_within_binding(db, connection, started_at):
    """Unseen history must have evidence of the current owner's activation."""
    if connection.binding_started_at:
        return bool(started_at and _utc(started_at) >= _utc(connection.binding_started_at))
    previous_owner = (await db.execute(select(RingCentralConnections.id).where(
        RingCentralConnections.ringcentral_account_id == connection.ringcentral_account_id,
        RingCentralConnections.ringcentral_extension_id == connection.ringcentral_extension_id,
        RingCentralConnections.employee_id != connection.employee_id,
    ))).first()
    return previous_owner is None


async def process_telephony_event(
    db: AsyncSession,
    payload: dict[str, Any],
    *,
    event_uuid: str | None = None,
) -> tuple[RingCentralCallRecords | None, bool]:
    connection = await _connection_for_event(db, payload)
    if not connection:
        return None, False
    employee_name = (
        await db.execute(select(Employees.name).where(Employees.id == connection.employee_id))
    ).scalar_one_or_none() or connection.employee_name
    body = payload.get("body") or {}
    extension_id = str(connection.ringcentral_extension_id or "")
    party = _event_party(body, extension_id)
    direction = str(party.get("direction") or body.get("direction") or "").strip().lower()
    from_phone = _party_phone(party.get("from") or body.get("from"))
    to_phone = _party_phone(party.get("to") or body.get("to"))
    remote_phone = to_phone if direction == "outbound" else from_phone
    telephony_session_id = str(body.get("telephonySessionId") or payload.get("telephonySessionId") or "").strip()
    session_id = str(party.get("sessionId") or body.get("sessionId") or "").strip()
    key = _provider_key(telephony_session_id, session_id, event_uuid)
    if not key:
        return None, False
    if telephony_session_id or session_id:
        existing = (await db.execute(select(RingCentralCallRecords.id).where(
            RingCentralCallRecords.ringcentral_account_id == connection.ringcentral_account_id,
            RingCentralCallRecords.ringcentral_extension_id == connection.ringcentral_extension_id,
            RingCentralCallRecords.sales_employee_id != connection.employee_id,
            or_(RingCentralCallRecords.telephony_session_id == telephony_session_id if telephony_session_id else False,
                RingCentralCallRecords.ringcentral_session_id == session_id if session_id else False),
        ))).first()
        if existing:
            return None, False
    event_time = _parse_datetime(body.get("eventTime") or payload.get("timestamp")) or datetime.now(timezone.utc)
    started_at = _parse_datetime(body.get("startTime")) or event_time
    provider_key = f"event:{connection.employee_id}:{connection.ringcentral_account_id}:{connection.ringcentral_extension_id}:{key}"
    item = (
        await db.execute(select(RingCentralCallRecords).where(RingCentralCallRecords.provider_key == provider_key))
    ).scalar_one_or_none()
    if not item:
        if not await _new_call_within_binding(db, connection, started_at):
            return None, False
        lead, task = await _match_lead_and_task(db, connection.employee_id, remote_phone, started_at)
        item = RingCentralCallRecords(
            provider_key=provider_key,
            sales_employee_id=connection.employee_id,
            sales_employee_name=employee_name,
            lead_id=lead.id if lead else None,
            task_id=task.id if task else None,
            ringcentral_account_id=connection.ringcentral_account_id,
            ringcentral_extension_id=connection.ringcentral_extension_id,
            telephony_session_id=telephony_session_id or None,
            ringcentral_session_id=session_id or None,
        )
        db.add(item)
    status_code = _status_code(party, body)
    normalized_status = status_code.lower()
    item.direction = direction or item.direction
    item.action = str(party.get("action") or body.get("action") or "").strip() or item.action
    item.provider_status = status_code or item.provider_status
    item.from_phone = from_phone or item.from_phone
    item.to_phone = to_phone or item.to_phone
    item.remote_phone = remote_phone or item.remote_phone
    item.started_at = item.started_at or started_at
    item.connected = bool(item.connected or normalized_status in CONNECTED_CODES)
    if normalized_status in CONNECTED_CODES:
        item.connected_at = item.connected_at or event_time
    terminal = normalized_status in TERMINAL_CODES
    if terminal:
        item.ended_at = event_time
    item.provider_sequence = body.get("sequence") or payload.get("sequence") or item.provider_sequence
    item.last_event_uuid = event_uuid or str(payload.get("uuid") or "").strip() or item.last_event_uuid
    item.last_event_at = event_time
    item.sync_status = "awaiting_call_log" if terminal else "event_received"
    connection.last_event_at = event_time
    await db.flush()
    return item, terminal


async def upsert_call_log_record(
    db: AsyncSession,
    connection: RingCentralConnections,
    record: dict[str, Any],
) -> RingCentralCallRecords | None:
    if connection.ringcentral_account_id and connection.ringcentral_extension_id:
        bindings = (await db.execute(select(RingCentralConnections.employee_id).where(
            RingCentralConnections.ringcentral_account_id == connection.ringcentral_account_id,
            RingCentralConnections.ringcentral_extension_id == connection.ringcentral_extension_id,
            RingCentralConnections.is_active.is_(True),
        ))).scalars().all()
        if len(bindings) > 1:
            connection.last_error = "分机绑定冲突，已暂停自动归属，请联系管理员核对"
            return None
        if bindings != [connection.employee_id]:
            # The provider fetch may have yielded while this authorization was
            # disconnected/rebound in another request. Recheck DB ownership.
            return None
    else:
        return None
    call_id = str(record.get("id") or "").strip()
    telephony_session_id = str(record.get("telephonySessionId") or "").strip()
    session_id = str(record.get("sessionId") or "").strip()
    key = _provider_key(call_id, telephony_session_id, session_id)
    if not key:
        return None
    employee_name = (
        await db.execute(select(Employees.name).where(Employees.id == connection.employee_id))
    ).scalar_one_or_none() or connection.employee_name
    item = None
    if call_id:
        item = (
            await db.execute(select(RingCentralCallRecords).where(
                RingCentralCallRecords.ringcentral_call_id == call_id,
                RingCentralCallRecords.ringcentral_account_id == connection.ringcentral_account_id,
                RingCentralCallRecords.ringcentral_extension_id == connection.ringcentral_extension_id))
        ).scalar_one_or_none()
        if item and item.sales_employee_id != connection.employee_id:
            # A new active authorization never transfers existing official call
            # evidence from the historical employee who actually owned it.
            return None
    if telephony_session_id or session_id:
        session_rows = (await db.execute(select(RingCentralCallRecords).where(
            or_(RingCentralCallRecords.telephony_session_id == telephony_session_id if telephony_session_id else False,
                RingCentralCallRecords.ringcentral_session_id == session_id if session_id else False),
            RingCentralCallRecords.ringcentral_account_id == connection.ringcentral_account_id,
            RingCentralCallRecords.ringcentral_extension_id == connection.ringcentral_extension_id,
        ).order_by(RingCentralCallRecords.id.desc()))).scalars().all()
        if any(row.sales_employee_id != connection.employee_id for row in session_rows):
            return None
        if not item:
            # A session can contain distinct official call records/legs.
            # Merge only an event without its own provider call identity.
            mergeable = [row for row in session_rows if not row.ringcentral_call_id
                         or (call_id and row.ringcentral_call_id == call_id)]
            item = mergeable[0] if mergeable else None
    direction = str(record.get("direction") or "").strip().lower()
    from_phone = _party_phone(record.get("from"))
    to_phone = _party_phone(record.get("to"))
    remote_phone = to_phone if direction == "outbound" else from_phone
    started_at = _parse_datetime(record.get("startTime"))
    # An unverified event may have arrived after activation while the actual
    # call began earlier. Its existence must not bypass the official fence.
    if not item or item.sync_status != "verified":
        if not await _new_call_within_binding(db, connection, started_at):
            return None
    if not item:
        lead, task = await _match_lead_and_task(db, connection.employee_id, remote_phone, started_at)
        item = RingCentralCallRecords(
            provider_key=f"log:{connection.employee_id}:{connection.ringcentral_account_id}:{connection.ringcentral_extension_id}:{key}",
            sales_employee_id=connection.employee_id,
            sales_employee_name=employee_name,
            lead_id=lead.id if lead else None,
            task_id=task.id if task else None,
            ringcentral_account_id=connection.ringcentral_account_id,
            ringcentral_extension_id=connection.ringcentral_extension_id,
        )
        db.add(item)
    result = str(record.get("result") or "").strip()
    duration = int(record.get("duration") or 0)
    item.ringcentral_call_id = call_id or item.ringcentral_call_id
    item.telephony_session_id = telephony_session_id or item.telephony_session_id
    item.ringcentral_session_id = session_id or item.ringcentral_session_id
    item.direction = direction or item.direction
    item.action = str(record.get("action") or "").strip() or item.action
    item.provider_status = "completed"
    item.provider_result = result or item.provider_result
    item.from_phone = from_phone or item.from_phone
    item.to_phone = to_phone or item.to_phone
    item.remote_phone = remote_phone or item.remote_phone
    item.started_at = started_at or item.started_at
    item.duration_seconds = duration
    item.connected = result.lower() in {"accepted", "answered", "call connected", "connected"}
    if item.connected and started_at:
        item.connected_at = item.connected_at or started_at
    if started_at:
        item.ended_at = started_at + timedelta(seconds=duration)
    item.recording_uri = _recording_uri(record) or item.recording_uri
    item.sync_status = "verified"
    item.synced_at = datetime.now(timezone.utc)
    await db.flush()
    activity = await _linked_activity(
        db, connection.employee_id, item.lead_id,
        await db.get(SalesDailyDialTasks, item.task_id) if item.task_id else None,
        remote_phone=item.remote_phone, call_started_at=item.started_at,
    )
    if activity:
        item.activity_id = activity.id
        activity.call_duration_seconds = duration
        activity.ringcentral_connected = item.connected
        activity.ringcentral_call_id = item.ringcentral_call_id
        activity.ringcentral_session_id = item.ringcentral_session_id or item.telephony_session_id
        activity.recording_uri = item.recording_uri
        activity.sync_status = "verified"
    connection.last_synced_at = datetime.now(timezone.utc)
    return item
