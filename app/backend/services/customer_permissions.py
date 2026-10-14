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

MODULES = ("basic", "contacts", "followups", "opportunities", "delivery", "renewals", "deals", "materials")
DEFAULT_INVITATION_SCOPES = {name: "read_only" if name in {"basic", "deals"} else "none" for name in MODULES}
ACCESS_LEVELS = ("none", "read_only", "read_write")
FINANCE_LEVELS = ("none", "status", "receipts", "profit")
GRANT_FIELDS = ("access_level", "scopes", "finance_access", "can_export", "can_delete", "can_reassign")
SHARED_BASIC_FIELDS = frozenset({
    "id", "customer_code", "business_name", "contact_name", "phone", "wechat", "email", "address",
    "city", "state", "country", "industry", "website", "google_business_link", "facebook_link",
    "instagram_link", "yelp_link", "tiktok_link", "has_ordering_system", "current_platform", "selected_platforms",
    "interested_packages", "monthly_orders", "source", "sales_person",
    "sales_employee_id", "level", "status", "created_at", "updated_at",
})



# Customer/platform fields predate typed schemas. Only recognized business
# platform names may leave the owner boundary; arbitrary legacy text is not a label.
SHARED_PLATFORM_NAMES = frozenset({
    "google_business", "google_ads", "facebook", "instagram", "yelp", "tiktok",
    "xiaohongshu", "x", "ads_campaign", "brand_website", "website",
    "google", "google business", "google business profile", "google ads", "google商家",
    "google商家管理", "facebook商家管理", "instagram商家管理", "yelp商家管理",
    "tiktok商家管理", "twitter", "小红书", "小红书管理", "广告投放", "品牌官网", "官网", "网站",
})


def shared_platform_names(raw: str | None) -> str | None:
    """Preserve standard JSON-list/CSV shape, never arbitrary/nested metadata."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    is_json = raw.startswith(("[", "{", '\"'))
    if is_json:
        try:
            entries = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(entries, list) or not all(isinstance(item, str) for item in entries):
            return None
    else:
        entries = raw.replace("，", ",").split(",")
    values = list(dict.fromkeys(item.strip() for item in entries
                              if item.strip().casefold() in SHARED_PLATFORM_NAMES))
    if not values:
        return None
    return json.dumps(values, ensure_ascii=False) if is_json else ",".join(values)


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
        "invitation_source": grant.invitation_source,
        "invitation_status": grant.invitation_status,
        "invited_at": grant.invited_at.isoformat() if grant.invited_at else None,
        "invited_by_id": grant.invited_by_id,
        "invited_by_name": grant.invited_by_name,
    }


def is_active_customer_invitation(grant: Any) -> bool:
    return bool(grant is not None and getattr(grant, "invitation_source", None) == "owner_invitation"
                and getattr(grant, "invitation_status", None) == "active"
                and getattr(grant, "access_level", "none") in {"read_only", "read_write"})


def _effective_permissions(user: Any, customer: Customers, grant: Any, config: dict) -> dict:
    owner = is_customer_owner(user)
    role = str(getattr(user, "role", "") or "").lower()
    active = is_active_customer_invitation(grant) and role != "sales_partner"
    if owner:
        sources = [{"code": "owner", "label": "老板完整权限"}]
    elif active:
        sources = [{"code": "owner_invitation", "label": "老板主动邀请"}]
    elif grant is not None and getattr(grant, "invitation_status", None) == "pending_review":
        sources = [{"code": "pending_review", "label": "旧授权待老板确认，尚未开放"}]
    elif grant is not None and getattr(grant, "invitation_status", None) == "revoked":
        sources = [{"code": "revoked", "label": "邀请已撤销"}]
    else:
        sources = [{"code": "uninvited", "label": "老板尚未邀请"}]
    level = "read_write" if owner else grant.access_level if active else "none"
    pages, buttons = set(config.get("pages", [])), set(config.get("buttons", []))
    admin_buttons = role in {"admin", "super_admin"}
    module_buttons = {
        "basic": {"customer_edit"}, "contacts": {"customer_edit"},
        "followups": {"follow_up_create", "follow_up_edit"},
        "opportunities": {"follow_up_create", "follow_up_edit"},
        "delivery": {"task_create", "task_edit"},
        "renewals": set(), "deals": set(),
        "materials": {"customer_edit", "media_account_create", "media_account_edit", "task_edit"},
    }
    scopes = (getattr(grant, "scopes", None) or {}) if active else {}
    modules = {}
    for name in MODULES:
        module_level = "read_write" if owner else scopes.get(name, "none")
        read = level != "none" and module_level in {"read_only", "read_write"}
        write = level == "read_write" and module_level == "read_write"
        page_allowed = owner or "/customers" in pages or (name in {"delivery", "materials"} and "/service-board" in pages)
        # Deals and renewals include payment-sensitive mutations; their general
        # write APIs remain owner-only, regardless of a collaboration toggle.
        write_allowed = owner or (name not in {"deals", "renewals"} and (admin_buttons or bool(buttons & module_buttons[name])))
        modules[name] = {"read": bool(read and page_allowed), "write": bool(write and page_allowed and write_allowed)}
    if active and not owner and any(scopes.get(m) == "read_write" and not modules[m]["write"] for m in MODULES):
        sources.append({"code": "role_limit", "label": "操作仍受员工角色功能权限限制"})
    finance = "profit" if owner else (getattr(grant, "finance_access", "none") or "none") if active else "none"
    action_allowed = lambda name: owner or (active and bool(getattr(grant, "can_" + name, False)))
    return {
        "access_level": level, "modules": modules, "finance_access": finance,
        "can_export": bool(action_allowed("export") and (owner or "customer_export" in buttons)),
        "can_delete": bool(level == "read_write" and action_allowed("delete") and (admin_buttons or bool(buttons & {"customer_delete", "follow_up_delete", "task_delete", "media_account_delete"}))),
        "can_reassign": bool(level == "read_write" and action_allowed("reassign") and (admin_buttons or "customer_assign" in buttons)),
        "can_manage_access": owner, "reveal_secrets": owner,
        "explicit": active,
        "invitation_status": "owner" if owner else getattr(grant, "invitation_status", "not_invited"),
        "invitation_source": "owner" if owner else getattr(grant, "invitation_source", None),
        "sources": sources,
    }


async def customer_permissions_for_rows(db: AsyncSession, user: Any, customers: list[Customers], *, config: dict | None = None) -> dict[int, dict]:
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
    return {row.id: _effective_permissions(user, row, grants.get(row.id), config) for row in customers}


async def get_customer_permissions(db: AsyncSession, user: Any, customer_id: int) -> dict:
    customer = await db.get(Customers, int(customer_id))
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return (await customer_permissions_for_rows(db, user, [customer]))[customer.id]


async def preview_customer_permissions(db: AsyncSession, employee: Any, customer: Customers, assignment: dict) -> dict:
    user = SimpleNamespace(id=str(employee.id), role=employee.role, name=employee.name)
    config = await _role_config(db, user)
    invitation = {**assignment, "invitation_source": "owner_invitation", "invitation_status": "active"}
    return _effective_permissions(user, customer, SimpleNamespace(**invitation), config)


async def require_customer_finance(db: AsyncSession, user: Any, customer_id: int, *, level: str = "status") -> dict:
    if level not in FINANCE_LEVELS[1:]:
        raise ValueError("Invalid finance permission level")
    permissions = await get_customer_permissions(db, user, customer_id)
    if permissions["access_level"] == "none":
        raise HTTPException(status_code=404, detail="Customer not found")
    if FINANCE_LEVELS.index(permissions["finance_access"]) < FINANCE_LEVELS.index(level):
        raise HTTPException(status_code=403, detail="该客户的财务资料尚未授权")
    return permissions
