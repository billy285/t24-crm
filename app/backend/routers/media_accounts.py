import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_admin_user, get_current_user
from schemas.auth import UserResponse
from services.customer_scope import ensure_customer_access
from services.media_accounts import (
    Media_accountsService,
    decrypt_media_account_password,
    has_media_account_password,
)
from services.operation_logs import Operation_logsService, build_server_operation_log_data
from services.role_permissions import load_role_permission_config, normalized_role

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/media_accounts", tags=["media_accounts"])


# ---------- Pydantic Schemas ----------
class Media_accountsData(BaseModel):
    """Entity data schema (for create/update)"""
    customer_id: int
    platform_name: str
    account_name: Optional[str] = None
    login_email: Optional[str] = None
    login_password: Optional[str] = None
    bound_phone: Optional[str] = None
    profile_url: Optional[str] = None
    account_status: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Media_accountsUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    customer_id: Optional[int] = None
    platform_name: Optional[str] = None
    account_name: Optional[str] = None
    login_email: Optional[str] = None
    login_password: Optional[str] = None
    bound_phone: Optional[str] = None
    profile_url: Optional[str] = None
    account_status: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Media_accountsResponse(BaseModel):
    """Entity response schema"""
    id: int
    user_id: Optional[str] = None
    customer_id: int
    platform_name: str
    account_name: Optional[str] = None
    login_email: Optional[str] = None
    login_password: Optional[str] = None
    has_password: bool = False
    bound_phone: Optional[str] = None
    profile_url: Optional[str] = None
    account_status: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Media_accountsListResponse(BaseModel):
    """List response schema"""
    items: List[Media_accountsResponse]
    total: int
    skip: int
    limit: int


class Media_accountsBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[Media_accountsData]


class Media_accountsBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: Media_accountsUpdateData


class Media_accountsBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[Media_accountsBatchUpdateItem]


class Media_accountsBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


class MediaAccountPasswordResponse(BaseModel):
    id: int
    login_password: str


DEFAULT_PASSWORD_VIEW_ROLES = {"super_admin", "admin"}
async def read_app_setting(db: AsyncSession, key: str, default: object):
    try:
        result = await db.execute(
            text("SELECT value_json FROM app_settings WHERE config_key = :key"),
            {"key": key},
        )
    except (OperationalError, ProgrammingError):
        # Authorization reads must never create/repair schema. Fresh databases
        # safely use versioned defaults until normal migrations create the table.
        await db.rollback()
        return default
    row = result.fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return default


async def can_view_media_account_password(current_user: UserResponse, db: AsyncSession) -> bool:
    role = normalized_role(current_user)
    if not role:
        return False

    role_permissions = await read_app_setting(db, "role_permissions", {})
    if isinstance(role_permissions, dict):
        role_config = role_permissions.get(role) or {}
        if not isinstance(role_config, dict):
            role_config = {}
        sensitive_fields = role_config.get("sensitiveFields") or {}
        # The modern per-role sensitive field is authoritative in both
        # directions.  In particular, an explicit false must revoke access
        # even if an older security_config still lists the role.
        if isinstance(sensitive_fields, dict) and "viewPassword" in sensitive_fields:
            return sensitive_fields.get("viewPassword") is True

        # Backward compatibility for role configurations that predate the
        # sensitiveFields object and granted the old button permission.
        buttons = role_config.get("buttons") or []
        if isinstance(buttons, list) and "view_password" in buttons:
            return True

    security_config = await read_app_setting(
        db,
        "security_config",
        {},
    )
    if isinstance(security_config, dict) and "passwordViewRoles" in security_config:
        password_view_roles = security_config.get("passwordViewRoles")
        if isinstance(password_view_roles, list):
            return role in password_view_roles

    # Fresh databases and truly legacy configurations retain the checked-in
    # admin default only when neither configurable source made a decision.
    return role in DEFAULT_PASSWORD_VIEW_ROLES


async def require_media_account_read_access(
    current_user: UserResponse,
    db: AsyncSession,
) -> None:
    config = await load_role_permission_config(db, current_user)
    if "/customers" not in config.get("pages", []):
        raise HTTPException(status_code=403, detail="You do not have permission to view media accounts")


async def require_media_account_permission(
    current_user: UserResponse,
    db: AsyncSession,
    permission: str,
) -> None:
    """Enforce media-account mutations at the API boundary.

    The browser permission gate is only presentation. Stored role permissions
    remain the source of truth, with checked-in defaults used for fresh/local
    databases that do not have app_settings yet.
    """
    config = await load_role_permission_config(db, current_user)
    buttons = config.get("buttons", [])
    if permission not in buttons:
        raise HTTPException(status_code=403, detail="You do not have permission to modify media accounts")


def serialize_media_account(item, *, include_password: bool = False) -> dict:
    raw_password = getattr(item, "login_password", None)
    data = Media_accountsResponse.model_validate(item, from_attributes=True).model_dump()
    data["has_password"] = has_media_account_password(raw_password)
    data["login_password"] = decrypt_media_account_password(raw_password) if include_password else None
    return data


# ---------- Routes ----------
@router.get("", response_model=Media_accountsListResponse)
async def query_media_accountss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query media_accountss with filtering, sorting, and pagination (user can only see their own records)"""
    await require_media_account_read_access(current_user, db)
    logger.debug(f"Querying media_accountss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = Media_accountsService(db)
    try:
        # Parse query JSON if provided
        query_dict = None
        if query:
            try:
                query_dict = json.loads(query)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid query JSON format")
        
        result = await service.get_list(
            skip=skip, 
            limit=limit,
            query_dict=query_dict,
            sort=sort,
            scope_user=current_user,
        )
        logger.debug(f"Found {result['total']} media_accountss")
        result["items"] = [serialize_media_account(item) for item in result["items"]]
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying media_accountss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=Media_accountsListResponse)
async def query_media_accountss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    # Query media_accountss with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying media_accountss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = Media_accountsService(db)
    try:
        # Parse query JSON if provided
        query_dict = None
        if query:
            try:
                query_dict = json.loads(query)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid query JSON format")

        result = await service.get_list(
            skip=skip,
            limit=limit,
            query_dict=query_dict,
            sort=sort
        )
        logger.debug(f"Found {result['total']} media_accountss")
        result["items"] = [serialize_media_account(item) for item in result["items"]]
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying media_accountss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=Media_accountsResponse)
async def get_media_accounts(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single media_accounts by ID (user can only see their own records)"""
    await require_media_account_read_access(current_user, db)
    logger.debug(f"Fetching media_accounts with id: {id}, fields={fields}")
    
    service = Media_accountsService(db)
    try:
        result = await service.get_by_id(id, scope_user=current_user)
        if not result:
            logger.warning(f"Media_accounts with id {id} not found")
            raise HTTPException(status_code=404, detail="Media_accounts not found")
        
        return serialize_media_account(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching media_accounts {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}/password", response_model=MediaAccountPasswordResponse)
async def get_media_account_password(
    id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reveal a media account password for authorized roles only."""
    await require_media_account_read_access(current_user, db)
    if not await can_view_media_account_password(current_user, db):
        raise HTTPException(status_code=403, detail="You do not have permission to view passwords")

    service = Media_accountsService(db)
    try:
        result = await service.get_by_id(id, scope_user=current_user)
        if not result:
            logger.warning(f"Media_accounts with id {id} not found for password reveal")
            raise HTTPException(status_code=404, detail="Media_accounts not found")

        plaintext_password = decrypt_media_account_password(result.login_password)
        # A password reveal is not successful unless its trusted server-side
        # audit record is durable.  Do this before returning the plaintext and
        # never rely on a second browser request that can be blocked or forged.
        await Operation_logsService(db).create(
            build_server_operation_log_data(
                current_user=current_user,
                request=request,
                customer_id=result.customer_id,
                action_type="view_password",
                action_detail=(
                    "查看媒体账号密码: "
                    f"account_id={result.id}; platform={result.platform_name}; "
                    f"account={result.account_name or '-'}"
                ),
            ),
            user_id=str(current_user.id),
        )
        return {
            "id": result.id,
            "login_password": plaintext_password,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revealing media_accounts password {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=Media_accountsResponse, status_code=201)
async def create_media_accounts(
    data: Media_accountsData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new media_accounts"""
    await require_media_account_permission(current_user, db, "media_account_create")
    await ensure_customer_access(db, current_user, data.customer_id)
    logger.debug(
        "Creating media account customer_id=%s platform=%s account=%s",
        data.customer_id,
        data.platform_name,
        data.account_name,
    )
    
    service = Media_accountsService(db)
    try:
        result = await service.create(data.model_dump(), user_id=str(current_user.id))
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create media_accounts")
        
        logger.info(f"Media_accounts created successfully with id: {result.id}")
        return serialize_media_account(result)
    except ValueError as e:
        logger.error(f"Validation error creating media_accounts: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating media_accounts: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[Media_accountsResponse], status_code=201)
async def create_media_accountss_batch(
    request: Media_accountsBatchCreateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple media_accountss in a single request"""
    await require_media_account_permission(current_user, db, "media_account_create")
    for item_data in request.items:
        await ensure_customer_access(db, current_user, item_data.customer_id)
    logger.debug(f"Batch creating {len(request.items)} media_accountss")
    
    service = Media_accountsService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump(), user_id=str(current_user.id))
            if result:
                results.append(serialize_media_account(result))
        
        logger.info(f"Batch created {len(results)} media_accountss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[Media_accountsResponse])
async def update_media_accountss_batch(
    request: Media_accountsBatchUpdateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update multiple media_accountss in a single request (requires ownership)"""
    await require_media_account_permission(current_user, db, "media_account_edit")
    logger.debug(f"Batch updating {len(request.items)} media_accountss")
    
    service = Media_accountsService(db)
    results = []

    # Validate the entire batch before the first write so one hidden customer
    # cannot cause a partial cross-scope update.
    for item in request.items:
        existing = await service.get_by_id(item.id, scope_user=current_user)
        if not existing:
            raise HTTPException(status_code=404, detail="Media_accounts not found")
        if item.updates.customer_id is not None:
            await ensure_customer_access(db, current_user, item.updates.customer_id)
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict, scope_user=current_user)
            if result:
                results.append(serialize_media_account(result))
        
        logger.info(f"Batch updated {len(results)} media_accountss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=Media_accountsResponse)
async def update_media_accounts(
    id: int,
    data: Media_accountsUpdateData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing media_accounts (requires ownership)"""
    await require_media_account_permission(current_user, db, "media_account_edit")
    if data.customer_id is not None:
        await ensure_customer_access(db, current_user, data.customer_id)
    logger.debug(
        "Updating media account id=%s fields=%s",
        id,
        sorted(data.model_fields_set - {"login_password"}),
    )

    service = Media_accountsService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict, scope_user=current_user)
        if not result:
            logger.warning(f"Media_accounts with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Media_accounts not found")
        
        logger.info(f"Media_accounts {id} updated successfully")
        return serialize_media_account(result)
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating media_accounts {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating media_accounts {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_media_accountss_batch(
    request: Media_accountsBatchDeleteRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple media_accountss by their IDs (requires ownership)"""
    await require_media_account_permission(current_user, db, "media_account_delete")
    logger.debug(f"Batch deleting {len(request.ids)} media_accountss")
    
    service = Media_accountsService(db)
    deleted_count = 0

    for item_id in request.ids:
        if not await service.get_by_id(item_id, scope_user=current_user):
            raise HTTPException(status_code=404, detail="Media_accounts not found")
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id, scope_user=current_user)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} media_accountss successfully")
        return {"message": f"Successfully deleted {deleted_count} media_accountss", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_media_accounts(
    id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single media_accounts by ID (requires ownership)"""
    await require_media_account_permission(current_user, db, "media_account_delete")
    logger.debug(f"Deleting media_accounts with id: {id}")
    
    service = Media_accountsService(db)
    try:
        success = await service.delete(id, scope_user=current_user)
        if not success:
            logger.warning(f"Media_accounts with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Media_accounts not found")
        
        logger.info(f"Media_accounts {id} deleted successfully")
        return {"message": "Media_accounts deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting media_accounts {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
