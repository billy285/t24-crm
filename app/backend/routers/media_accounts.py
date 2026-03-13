import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.media_accounts import Media_accountsService
from dependencies.auth import get_current_user
from schemas.auth import UserResponse

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
            user_id=str(current_user.id),
        )
        logger.debug(f"Found {result['total']} media_accountss")
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
    logger.debug(f"Fetching media_accounts with id: {id}, fields={fields}")
    
    service = Media_accountsService(db)
    try:
        result = await service.get_by_id(id, user_id=str(current_user.id))
        if not result:
            logger.warning(f"Media_accounts with id {id} not found")
            raise HTTPException(status_code=404, detail="Media_accounts not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching media_accounts {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=Media_accountsResponse, status_code=201)
async def create_media_accounts(
    data: Media_accountsData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new media_accounts"""
    logger.debug(f"Creating new media_accounts with data: {data}")
    
    service = Media_accountsService(db)
    try:
        result = await service.create(data.model_dump(), user_id=str(current_user.id))
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create media_accounts")
        
        logger.info(f"Media_accounts created successfully with id: {result.id}")
        return result
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
    logger.debug(f"Batch creating {len(request.items)} media_accountss")
    
    service = Media_accountsService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump(), user_id=str(current_user.id))
            if result:
                results.append(result)
        
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
    logger.debug(f"Batch updating {len(request.items)} media_accountss")
    
    service = Media_accountsService(db)
    results = []
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict, user_id=str(current_user.id))
            if result:
                results.append(result)
        
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
    logger.debug(f"Updating media_accounts {id} with data: {data}")

    service = Media_accountsService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict, user_id=str(current_user.id))
        if not result:
            logger.warning(f"Media_accounts with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Media_accounts not found")
        
        logger.info(f"Media_accounts {id} updated successfully")
        return result
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
    logger.debug(f"Batch deleting {len(request.ids)} media_accountss")
    
    service = Media_accountsService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id, user_id=str(current_user.id))
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
    logger.debug(f"Deleting media_accounts with id: {id}")
    
    service = Media_accountsService(db)
    try:
        success = await service.delete(id, user_id=str(current_user.id))
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