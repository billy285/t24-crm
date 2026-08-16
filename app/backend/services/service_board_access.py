"""Role-permission checks shared by service-progress and service-task APIs."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.auth import UserResponse
from services.role_permissions import load_role_permission_config, normalized_role


SERVICE_BOARD_PAGE = "/service-board"
SERVICE_BOARD_READ_PAGES = {SERVICE_BOARD_PAGE, "/customers"}
SERVICE_BOARD_ADMIN_ROLES = {"admin", "super_admin"}


async def require_service_board_access(
    db: AsyncSession,
    current_user: UserResponse,
    permission: str | None = None,
) -> None:
    """Authorize service-board reads and writes from their real consumers.

    Customer detail embeds read-only delivery history, so reads accept either
    the customer workspace or the service board. Mutations still require the
    service-board page plus the configured task button.
    """
    role = normalized_role(current_user)
    config = await load_role_permission_config(db, current_user)
    pages = set(config.get("pages", []))
    if permission:
        if SERVICE_BOARD_PAGE not in pages:
            raise HTTPException(status_code=403, detail="Service board access required")
    elif not pages.intersection(SERVICE_BOARD_READ_PAGES):
        raise HTTPException(status_code=403, detail="Customer or service board access required")

    if permission and permission not in config.get("buttons", []):
        # Deletion remains an administrator escape hatch for recovery, while
        # normal roles must explicitly hold task_delete.
        if permission != "task_delete" or role not in SERVICE_BOARD_ADMIN_ROLES:
            raise HTTPException(status_code=403, detail=f"{permission} permission required")
