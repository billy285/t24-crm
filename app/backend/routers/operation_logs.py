import json
import logging
from typing import List, Optional

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.customer_scope import ensure_customer_access
from services.operation_logs import (
    CLIENT_OPERATION_ACTION_TYPES,
    MAX_OPERATION_BATCH_SIZE,
    MAX_OPERATION_DETAIL_LENGTH,
    Operation_logsService,
    build_server_operation_log_data,
)
from dependencies.auth import get_admin_user, get_current_user
from schemas.auth import UserResponse

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/operation_logs", tags=["operation_logs"])


# ---------- Pydantic Schemas ----------
class Operation_logsData(BaseModel):
    """Append-only, explicitly non-audit user note."""
    customer_id: Optional[int] = Field(default=None, gt=0)
    action_type: str
    action_detail: Optional[str] = Field(default=None, max_length=MAX_OPERATION_DETAIL_LENGTH)
    # Accepted only for compatibility with already-loaded browser bundles.
    # The route always discards and replaces these server-owned fields.
    user_id: Optional[str] = None
    operator_name: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: Optional[datetime] = None

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, value: str) -> str:
        if value not in CLIENT_OPERATION_ACTION_TYPES:
            raise ValueError("Unsupported operation action type")
        return value


class Operation_logsResponse(BaseModel):
    """Entity response schema"""
    id: int
    user_id: Optional[str] = None
    customer_id: Optional[int] = None
    action_type: str
    action_detail: Optional[str] = None
    operator_name: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Operation_logsListResponse(BaseModel):
    """List response schema"""
    items: List[Operation_logsResponse]
    total: int
    skip: int
    limit: int


class Operation_logsBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[Operation_logsData] = Field(min_length=1, max_length=MAX_OPERATION_BATCH_SIZE)


# ---------- Routes ----------
@router.get("", response_model=Operation_logsListResponse)
async def query_operation_logss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query operation_logss with filtering, sorting, and pagination (user can only see their own records)"""
    logger.debug(f"Querying operation_logss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = Operation_logsService(db)
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
        logger.debug(f"Found {result['total']} operation_logss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying operation_logss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=Operation_logsListResponse)
async def query_operation_logss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    # Query operation_logss with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying operation_logss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = Operation_logsService(db)
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
        )
        logger.debug(f"Found {result['total']} operation_logss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying operation_logss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=Operation_logsResponse)
async def get_operation_logs(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single operation_logs by ID (user can only see their own records)"""
    logger.debug(f"Fetching operation_logs with id: {id}, fields={fields}")
    
    service = Operation_logsService(db)
    try:
        result = await service.get_by_id(id, user_id=str(current_user.id))
        if not result:
            logger.warning(f"Operation_logs with id {id} not found")
            raise HTTPException(status_code=404, detail="Operation_logs not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching operation_logs {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=Operation_logsResponse, status_code=201)
async def create_operation_logs(
    data: Operation_logsData,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Append a user note; this endpoint never creates a trusted audit event."""
    logger.debug(
        "Creating operation log customer_id=%s action_type=%s",
        data.customer_id,
        data.action_type,
    )
    
    service = Operation_logsService(db)
    try:
        if data.customer_id is not None:
            await ensure_customer_access(db, current_user, data.customer_id)
        trusted_data = build_server_operation_log_data(
            current_user=current_user,
            request=request,
            customer_id=data.customer_id,
            action_type=data.action_type,
            action_detail=data.action_detail,
        )
        result = await service.create(trusted_data, user_id=str(current_user.id))
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create operation_logs")
        
        logger.info(f"Operation_logs created successfully with id: {result.id}")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error creating operation_logs: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating operation_logs: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[Operation_logsResponse], status_code=201)
async def create_operation_logss_batch(
    request: Operation_logsBatchCreateRequest,
    http_request: Request,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Append a bounded batch of non-audit user notes (admin only)."""
    logger.debug(f"Batch creating {len(request.items)} operation_logss")
    
    service = Operation_logsService(db)
    results = []
    
    try:
        for item_data in request.items:
            if item_data.customer_id is not None:
                await ensure_customer_access(db, current_user, item_data.customer_id)
        for item_data in request.items:
            trusted_data = build_server_operation_log_data(
                current_user=current_user,
                request=http_request,
                customer_id=item_data.customer_id,
                action_type=item_data.action_type,
                action_detail=item_data.action_detail,
            )
            result = await service.create(
                trusted_data,
                user_id=str(current_user.id),
                commit=False,
            )
            if result:
                results.append(result)
        await db.commit()
        for result in results:
            await db.refresh(result)
        
        logger.info(f"Batch created {len(results)} operation_logss successfully")
        return results
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")
