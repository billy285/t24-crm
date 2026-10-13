"""Customer sharing decisions and safe, explainable effective permissions."""
from types import SimpleNamespace
from typing import Any
import json

from fastapi import Depends, HTTPException, Response
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_user
from models.customers import Customers
from models.customer_access_grants import CustomerAccessGrant
from schemas.auth import UserResponse
from services.role_permissions import FIXED_ROLE_PAGES, normalized_role

MODULES = ("basic", "followups", "delivery", "materials")
ACCESS_LEVELS = ("none", "read_only", "read_write")
FINANCE_LEVELS = ("none", "status", "receipts", "profit")
GRANT_FIELDS = ("access_level", "scopes", "finance_access", "can_export", "can_delete", "can_reassign")


async def _role_config(db: AsyncSession, user: Any) -> dict:
    """Read role limits without DDL or rolling back the caller's transaction."""
    from routers.app_config import DEFAULT_APP_CONFIGS
    role = normalized_role(user)
    defaults = DEFAULT_APP_CONFIGS["role_permissions"].get(role) or {}
    stored = {}
    connection = await db.connection()
    if await connection.run_sync(lambda conn: inspect(conn).has_table("app_settings")):
        raw = (await db.execute(text("SELECT value_json FROM app_settings WHERE config_key = 'role_permissions'"))).scalar_one_or_none()
        try:
            values = json.loads(raw) if raw else {}
            if isinstance(values, dict) and isinstance(values.get(role), dict):
                stored = values[role]
        except (ValueError, TypeError):
            pass
    pages = stored.get("pages") if isinstance(stored.get("pages"), list) else defaults.get("pages", [])
    buttons = stored.get("buttons") if isinstance(stored.get("buttons"), list) else defaults.get("buttons", [])
    return {"pages": list(dict.fromkeys([*pages, *FIXED_ROLE_PAGES.get(role, ())])), "buttons": buttons}


def is_customer_owner(user: Any) -> bool:
    # get_current_user already verifies employee status/session and canonicalizes
    # legacy owner roles. Never promote an ordinary administrator here.
    return str(getattr(user, "role", "") or "").lower() == "super_admin"


async def get_customer_owner_user(response: Response, current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    if not is_customer_owner(current_user):
        raise HTTPException(status_code=403, detail="仅老板可以管理客户共享和私密资料")
    response.headers["Cache-Control"] = "private, no-store"
    return current_user


def grant_snapshot(grant: Any) -> dict:
    return {
        "employee_id": int(grant.employee_id),
        "access_level": grant.access_level or "read_only",
        "scopes": dict(grant.scopes or {}),
        "finance_access": grant.finance_access or "none",
        "can_export": bool(grant.can_export),
        "can_delete": bool(grant.can_delete),
        "can_reassign": bool(grant.can_reassign),
    }


def _effective_permissions(user: Any, customer: Customers, grant: Any, inherited: bool, config: dict) -> dict:
    owner = is_customer_owner(user)
    role = str(getattr(user, "role", "") or "").lower()
    sources = []
    if owner:
        sources.append({"code": "owner", "label": "老板完整权限"})
    elif grant is not None:
        sources.append({"code": "explicit", "label": "老板单独设置（覆盖归属与部门继承）"})
    elif inherited:
        direct = str(customer.sales_employee_id or "") == str(user.id) or (
            customer.sales_employee_id is None and customer.sales_person == getattr(user, "name", None))
        sources.append({"code": "sales_owner" if direct else "department", "label": "客户负责人继承" if direct else "销售部门继承"})
    else:
        sources.append({"code": "unshared", "label": "未获客户授权"})
    level = "read_write" if owner or (grant is None and inherited) else (getattr(grant, "access_level", "none") or "none")
    if role == "sales_partner":
        level = "none"
    pages = set(config.get("pages", []))
    buttons = set(config.get("buttons", []))
    admin_buttons = role in {"admin", "super_admin"}
    module_buttons = {"basic": {"customer_edit"}, "followups": {"follow_up_create", "follow_up_edit"},
                      "delivery": {"task_create", "task_edit"}, "materials": {"customer_edit", "media_account_create", "media_account_edit", "task_edit"}}
    scopes = (getattr(grant, "scopes", None) or {}) if grant is not None else {}
    modules = {}
    for name in MODULES:
        module_level = "read_write" if owner else scopes.get(name, level)
        read = level != "none" and module_level in {"read_only", "read_write"}
        write = level == "read_write" and module_level == "read_write"
        # Keep global role page/button boundaries. Effective output explains the
        # intersection, not a promise that a grant changes system roles.
        page_allowed = owner or "/customers" in pages or (name != "basic" and "/service-board" in pages)
        modules[name] = {"read": bool(read and page_allowed), "write": bool(write and page_allowed and (admin_buttons or buttons & module_buttons[name]))}
    if level != "none" and not owner and not all(modules[m]["write"] for m in MODULES):
        sources.append({"code": "role_limit", "label": "操作仍受员工角色功能权限限制"})
    finance = "profit" if owner else (getattr(grant, "finance_access", "none") or "none")
    if level == "none":
        finance = "none"
    action_allowed = lambda name: owner or (level != "none" and bool(getattr(grant, "can_" + name, False)))
    return {
        "access_level": level,
        "modules": modules,
        "finance_access": finance,
        "can_export": bool(action_allowed("export") and (owner or "customer_export" in buttons)),
        "can_delete": bool(level == "read_write" and action_allowed("delete") and (admin_buttons or bool(buttons & {"customer_delete", "follow_up_delete", "task_delete", "media_account_delete"}))),
        "can_reassign": bool(level == "read_write" and action_allowed("reassign") and (admin_buttons or "customer_assign" in buttons)),
        "can_manage_access": owner,
        "reveal_secrets": owner,
        "explicit": grant is not None,
        "sources": sources,
    }


async def customer_permissions_for_rows(db: AsyncSession, user: Any, customers: list[Customers], *, config: dict | None = None) -> dict[int, dict]:
    from services.customers import CustomersService
    if not customers:
        return {}
    config = config if config is not None else await _role_config(db, user)
    try:
        employee_id = int(user.id)
    except (TypeError, ValueError):
        employee_id = -1
    ids = [row.id for row in customers]
    grants = {row.customer_id: row for row in (await db.execute(select(CustomerAccessGrant).where(
        CustomerAccessGrant.employee_id == employee_id, CustomerAccessGrant.customer_id.in_(ids)
    ))).scalars()}
    inherited_ids = set()
    filters = CustomersService._owner_filters_for_user(user, employee_id, str(user.role or "").lower())
    if filters:
        from sqlalchemy import or_
        inherited_ids = set((await db.execute(select(Customers.id).where(Customers.id.in_(ids), or_(*filters)))).scalars())
    return {row.id: _effective_permissions(user, row, grants.get(row.id), row.id in inherited_ids, config) for row in customers}


async def get_customer_permissions(db: AsyncSession, user: Any, customer_id: int) -> dict:
    customer = await db.get(Customers, int(customer_id))
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return (await customer_permissions_for_rows(db, user, [customer]))[customer.id]


async def preview_customer_permissions(db: AsyncSession, employee: Any, customer: Customers, assignment: dict) -> dict:
    user = SimpleNamespace(id=str(employee.id), role=employee.role, name=employee.name)
    config = await _role_config(db, user)
    return _effective_permissions(user, customer, SimpleNamespace(**assignment), False, config)


async def require_customer_finance(db: AsyncSession, user: Any, customer_id: int, *, level: str = "status") -> dict:
    if level not in FINANCE_LEVELS[1:]:
        raise ValueError("Invalid finance permission level")
    permissions = await get_customer_permissions(db, user, customer_id)
    if permissions["access_level"] == "none":
        raise HTTPException(status_code=404, detail="Customer not found")
    if FINANCE_LEVELS.index(permissions["finance_access"]) < FINANCE_LEVELS.index(level):
        raise HTTPException(status_code=403, detail="该客户的财务资料尚未授权")
    return permissions
