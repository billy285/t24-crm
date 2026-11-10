"""Server-written sync-window evidence, separate from provider call facts.

The existing append-only operation log stores compact JSON; its public writer
only accepts user_note. No call, token, phone number or new schema is stored here.
Fetching every page proves a fetch window, never completeness of provider data.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from models.operation_logs import Operation_logs

ACTION_TYPE = "ringcentral_sync_window"


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def stamp(value):
    return utc(value).isoformat()


def parsed(value):
    try:
        return utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def binding_key(connection):
    if not connection or not connection.ringcentral_account_id or not connection.ringcentral_extension_id:
        return None
    started = connection.binding_started_at or connection.created_at
    parts = [connection.employee_id, connection.ringcentral_account_id, connection.ringcentral_extension_id,
             stamp(started) if started else None]
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def record_window(db, connection, *, binding, date_from, date_to, status, pages=0,
                  fetched=0, saved=0, skipped=0, fully_paginated=False, error_code=None):
    """Append within the caller's transaction; never infer evidence from last_synced_at."""
    now = datetime.now(timezone.utc)
    evidence = dict(version=1, employee_id=connection.employee_id, binding=binding,
                    requested_from=stamp(date_from), requested_to=stamp(date_to),
                    finished_at=stamp(now), status=status, pages=int(pages), fetched=int(fetched),
                    saved=int(saved), skipped=int(skipped), fully_paginated=bool(fully_paginated),
                    error_code=error_code)
    db.add(Operation_logs(user_id=str(connection.employee_id), action_type=ACTION_TYPE,
                          action_detail=json.dumps(evidence, separators=(",", ":")),
                          operator_name=connection.employee_name, created_at=now))
    return evidence


def summarize_windows(windows, start, end):
    start, end = utc(start), utc(end)
    intervals = []
    for item in windows:
        left, right = parsed(item.get("requested_from")), parsed(item.get("requested_to"))
        if (item.get("status") == "completed" and item.get("fully_paginated") is True
                and item.get("skipped") == 0 and left and right and left < right):
            left, right = max(left, start), min(right, end)
            if left < right:
                intervals.append((left, right))
    merged = []
    for left, right in sorted(intervals):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    gaps, cursor = [], start
    for left, right in merged:
        if cursor < left:
            gaps.append(dict(start=stamp(cursor), end=stamp(left)))
        cursor = max(cursor, right)
    if cursor < end:
        gaps.append(dict(start=stamp(cursor), end=stamp(end)))
    status = "window_fetched" if merged and not gaps else "gaps" if merged else "unknown"
    latest = windows[0] if windows else None
    return dict(status=status, data_complete=False, requested_from=stamp(start), requested_to=stamp(end),
                fetched_ranges=[dict(start=stamp(a), end=stamp(b)) for a, b in merged],
                unverified_ranges=gaps, unverified_range_count=len(gaps),
                last_attempt=latest, recent_attempts=windows[:5],
                needs_retry=bool(latest and latest.get("status") != "completed"),
                message="分页拉取记录可核对；未核验区间不代表没有拨打。运营商可能延迟入账，历史完整性仍待核验。")


async def connection_coverage(db, connections, *, start=None, end=None):
    end = utc(end or datetime.now(timezone.utc))
    start = utc(start or end - timedelta(days=7))
    identities = {item.employee_id: binding_key(item) for item in connections if binding_key(item)}
    grouped = {employee_id: [] for employee_id in identities}
    if identities:
        rows = (await db.execute(select(Operation_logs).where(
            Operation_logs.action_type == ACTION_TYPE,
            Operation_logs.user_id.in_([str(value) for value in identities]),
            Operation_logs.created_at >= start,
        ).order_by(Operation_logs.created_at.desc(), Operation_logs.id.desc()).limit(2000))).scalars().all()
        for row in rows:
            try:
                item = json.loads(row.action_detail or "")
            except (ValueError, TypeError):
                continue
            employee_id = item.get("employee_id") if isinstance(item, dict) else None
            if (employee_id in identities and item.get("version") == 1
                    and row.user_id == str(employee_id) and item.get("binding") == identities[employee_id]):
                grouped[employee_id].append(item)
    return {employee_id: summarize_windows(items, start, end) for employee_id, items in grouped.items()}
