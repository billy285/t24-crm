"""Passive, scoped RingCentral connection health; never refreshes OAuth tokens."""
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.employees import Employees
from models.ringcentral_connections import RingCentralConnections


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def passive_connection_status(connection, *, configured=True, binding_conflict=False):
    if connection is None:
        return dict(configured=configured, connected=False, degraded=False, needs_reconnect=False,
                    realtime_sync_enabled=False, sync_health="disconnected", authorization_status="not_connected",
                    extension_number=None, last_synced_at=None, last_event_at=None, last_error=None,
                    webhook_status=None, webhook_expires_at=None, binding_conflict=False,
                    message="等待销售连接自己的 RingCentral 账号" if configured else "等待系统管理员完成服务器凭证配置")
    now = datetime.now(timezone.utc)
    active = bool(connection.is_active)
    identity_complete = bool(connection.ringcentral_account_id and connection.ringcentral_extension_id)
    webhook_status = str(connection.webhook_subscription_status or "").strip().lower()
    webhook_current = bool(connection.webhook_expires_at and _utc(connection.webhook_expires_at) > now)
    token_current = bool(connection.token_expires_at and _utc(connection.token_expires_at) > now)
    ready = bool(active and identity_complete and configured and webhook_status == "active" and webhook_current and token_current
                 and not connection.last_error and not binding_conflict)
    health = "enabled" if ready else "attention" if active or binding_conflict else "disconnected"
    message = (
        "分机绑定冲突，请联系管理员核对；该分机暂不用于自动归属" if binding_conflict else
        "等待系统管理员完成服务器凭证配置" if not configured else
        "RingCentral 授权已失效或已断开，请销售本人重新连接" if not active else
        "账号缺少账户或分机信息，请销售本人重新连接" if not identity_complete else
        "访问授权待刷新，请销售本人打开工作台检查连接" if not token_current else
        "实时通话订阅已过期或未启用，请销售本人修复同步" if not (webhook_current and webhook_status == "active") else
        "通话同步异常，请销售本人检查连接" if connection.last_error else
        "实时通话同步已启用"
    )
    return dict(configured=configured, connected=active, degraded=health == "attention",
                needs_reconnect=not active or not identity_complete, realtime_sync_enabled=ready, sync_health=health,
                authorization_status="connected" if active else "reconnect_required",
                extension_number=connection.extension_number, connected_at=connection.binding_started_at or connection.created_at,
                binding_started_at=connection.binding_started_at,
                last_synced_at=connection.last_synced_at, last_event_at=connection.last_event_at,
                last_error=connection.last_error, webhook_status=webhook_status or None,
                webhook_expires_at=connection.webhook_expires_at, binding_conflict=binding_conflict, message=message)


async def team_connection_statuses(db: AsyncSession, employee_ids: list[int], *, configured=True) -> list[dict]:
    """Return only the requested employees; disclose no identity behind a conflict."""
    if not employee_ids:
        return []
    employees = (await db.execute(select(Employees).where(Employees.id.in_(employee_ids))
                                 .order_by(Employees.name, Employees.id))).scalars().all()
    # Inactive authorizations remain historical records, not current owners.
    # Only active binding counts are used; other teams' names never escape.
    connections = (await db.execute(select(RingCentralConnections))).scalars().all()
    counts = Counter((row.ringcentral_account_id, row.ringcentral_extension_id) for row in connections
                     if row.is_active and row.ringcentral_account_id and row.ringcentral_extension_id)
    by_employee = {row.employee_id: row for row in connections}
    items = []
    for employee in employees:
        connection = by_employee.get(employee.id)
        conflict = bool(connection and connection.is_active and connection.ringcentral_account_id and connection.ringcentral_extension_id
                        and counts[(connection.ringcentral_account_id, connection.ringcentral_extension_id)] > 1)
        items.append(dict(employee_id=employee.id, employee_name=employee.name,
                          **passive_connection_status(connection, configured=configured, binding_conflict=conflict)))
    return items


def connection_summary(items: list[dict]) -> dict:
    return dict(total=len(items), ready=sum(row["sync_health"] == "enabled" for row in items),
                attention=sum(row["sync_health"] == "attention" for row in items),
                not_connected=sum(row["sync_health"] == "disconnected" for row in items))
