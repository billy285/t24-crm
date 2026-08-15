import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from routers.app_config import DEFAULT_APP_CONFIGS
from schemas.auth import UserResponse


ROLE_ALIASES = {
    "administrator": "admin",
    "system_admin": "admin",
    "operations": "ops",
    "operation": "ops",
    "designer": "design",
}

FIXED_ROLE_PAGES = {
    # These are product boundaries, not optional UI customizations. Stored
    # role settings may add pages but cannot remove the customer workspace
    # needed for scoped sales/customer-detail workflows.
    "sales": ("/customers", "/sales-leads"),
    "sales_manager": ("/customers", "/merchant-pool", "/sales-leads"),
}


def normalized_role(user: UserResponse) -> str:
    role = str(user.role or "").strip().lower()
    return ROLE_ALIASES.get(role, role)


async def load_role_permission_config(db: AsyncSession, user: UserResponse) -> dict[str, Any]:
    """Load the configured role contract without creating or repairing schema."""
    role = normalized_role(user)
    defaults = DEFAULT_APP_CONFIGS["role_permissions"].get(role) or {}
    stored_role: dict[str, Any] = {}
    try:
        row = (await db.execute(
            text("SELECT value_json FROM app_settings WHERE config_key = 'role_permissions'")
        )).first()
        if row:
            parsed = json.loads(row[0])
            if isinstance(parsed, dict) and isinstance(parsed.get(role), dict):
                stored_role = parsed[role]
    except (OperationalError, ProgrammingError, json.JSONDecodeError, TypeError):
        # Fresh/local databases may not have app_settings. Permission reads stay
        # side-effect free and fall back to the versioned defaults.
        await db.rollback()

    configured_pages = stored_role.get("pages") if isinstance(stored_role.get("pages"), list) else defaults.get("pages", [])
    pages = list(dict.fromkeys([
        *(str(page) for page in configured_pages),
        *FIXED_ROLE_PAGES.get(role, ()),
    ]))

    return {
        "pages": pages,
        "buttons": stored_role.get("buttons") if isinstance(stored_role.get("buttons"), list) else defaults.get("buttons", []),
        "dataScope": stored_role.get("dataScope") or defaults.get("dataScope", "self"),
    }


async def require_button_permission(
    db: AsyncSession,
    user: UserResponse,
    permission: str,
    *,
    admin_override: bool = False,
) -> None:
    role = normalized_role(user)
    if admin_override and role in {"admin", "super_admin"}:
        return
    config = await load_role_permission_config(db, user)
    if permission not in {str(item) for item in config.get("buttons", [])}:
        raise HTTPException(status_code=403, detail=f"{permission} permission required")


async def require_any_page_permission(
    db: AsyncSession,
    user: UserResponse,
    pages: set[str],
) -> None:
    config = await load_role_permission_config(db, user)
    allowed_pages = {str(item) for item in config.get("pages", [])}
    if not (allowed_pages & pages):
        raise HTTPException(status_code=403, detail="Customer workspace access required")
