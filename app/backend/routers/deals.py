import json
import logging
from typing import List, Literal, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user, get_finance_user
from schemas.auth import UserResponse
from services.deals import DealsService
from services.deal_payment_sync import sync_payment_from_deal, unlink_synced_payment_for_deal
from services.deal_finalize import (
    deal_finalize_lock,
    ensure_service_board,
    finalize_subscription_and_customer,
    load_deal_for_finalize,
)
from services.service_board_access import require_service_board_access

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/deals", tags=["deals"], dependencies=[Depends(get_current_user)])


# ---------- Pydantic Schemas ----------
class DealsData(BaseModel):
    """Entity data schema (for create/update)"""
    source_payment_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    customer_id: int
    customer_name: Optional[str] = None
    sales_employee_id: Optional[int] = None
    sales_name: Optional[str] = None
    product_type: str
    package_name: Optional[str] = None
    package_platforms: Optional[str] = None
    billing_cycle: Optional[str] = None
    deal_amount: float
    is_paid: Optional[bool] = None
    service_start_date: Optional[datetime] = None
    service_end_date: Optional[datetime] = None
    needs_group: Optional[bool] = None
    is_handed_over: Optional[bool] = None
    is_transferred_ops: Optional[bool] = None
    notes: Optional[str] = None
    deal_date: Optional[datetime] = None
    created_at: Optional[datetime] = None


class DealsUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    source_payment_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    sales_employee_id: Optional[int] = None
    sales_name: Optional[str] = None
    product_type: Optional[str] = None
    package_name: Optional[str] = None
    package_platforms: Optional[str] = None
    billing_cycle: Optional[str] = None
    deal_amount: Optional[float] = None
    is_paid: Optional[bool] = None
    service_start_date: Optional[datetime] = None
    service_end_date: Optional[datetime] = None
    needs_group: Optional[bool] = None
    is_handed_over: Optional[bool] = None
    is_transferred_ops: Optional[bool] = None
    notes: Optional[str] = None
    deal_date: Optional[datetime] = None
    created_at: Optional[datetime] = None


class DealsResponse(BaseModel):
    """Entity response schema"""
    id: int
    source_payment_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    customer_id: int
    customer_name: Optional[str] = None
    sales_employee_id: Optional[int] = None
    sales_name: Optional[str] = None
    product_type: str
    package_name: Optional[str] = None
    package_platforms: Optional[str] = None
    billing_cycle: Optional[str] = None
    deal_amount: Optional[float] = None
    is_paid: Optional[bool] = None
    service_start_date: Optional[datetime] = None
    service_end_date: Optional[datetime] = None
    needs_group: Optional[bool] = None
    is_handed_over: Optional[bool] = None
    is_transferred_ops: Optional[bool] = None
    notes: Optional[str] = None
    deal_date: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DealsListResponse(BaseModel):
    """List response schema"""
    items: List[DealsResponse]
    total: int
    skip: int
    limit: int


class DealsBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[DealsData]


class DealsBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: DealsUpdateData


class DealsBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[DealsBatchUpdateItem]


class DealsBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


class DealFinalizeRequest(BaseModel):
    ensure_subscription: bool = False
    auto_renew: bool = False
    create_service_board: bool = False


class DealFinalizeStep(BaseModel):
    status: Literal["completed", "skipped", "failed"]
    message: str
    resource_id: Optional[int] = None
    created_count: int = 0
    retryable: bool = False


class DealFinalizeResponse(BaseModel):
    deal_id: int
    complete: bool
    retryable: bool
    steps: dict[str, DealFinalizeStep]


FINANCE_DETAIL_ROLES = {"admin", "super_admin", "finance"}


def _deal_for_user(item, user: UserResponse) -> DealsResponse:
    response = DealsResponse.model_validate(item)
    if str(user.role or "").lower() in FINANCE_DETAIL_ROLES:
        return response
    return response.model_copy(update={
        "source_payment_id": None,
        "deal_amount": None,
        "is_paid": None,
    })


def _failed_finalize_step(message: str, *, retryable: bool = True) -> dict:
    return {
        "status": "failed",
        "message": message,
        "resource_id": None,
        "created_count": 0,
        "retryable": retryable,
    }


# ---------- Routes ----------
@router.get("", response_model=DealsListResponse)
async def query_dealss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query dealss with filtering, sorting, and pagination"""
    logger.debug(f"Querying dealss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = DealsService(db)
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
        result["items"] = [_deal_for_user(item, current_user) for item in result["items"]]
        logger.debug(f"Found {result['total']} dealss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying dealss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=DealsListResponse)
async def query_dealss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Query dealss with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying dealss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = DealsService(db)
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
        result["items"] = [_deal_for_user(item, current_user) for item in result["items"]]
        logger.debug(f"Found {result['total']} dealss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying dealss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=DealsResponse)
async def get_deals(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single deals by ID"""
    logger.debug(f"Fetching deals with id: {id}, fields={fields}")
    
    service = DealsService(db)
    try:
        result = await service.get_by_id(id, scope_user=current_user)
        if not result:
            logger.warning(f"Deals with id {id} not found")
            raise HTTPException(status_code=404, detail="Deals not found")
        
        return _deal_for_user(result, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching deals {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=DealsResponse, status_code=201)
async def create_deals(
    data: DealsData,
    _finance_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new deals"""
    logger.debug(f"Creating new deals with data: {data}")
    
    service = DealsService(db)
    try:
        result = await service.create(data.model_dump(), commit=False)
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create deals")

        await sync_payment_from_deal(db, result, commit=False)
        await db.commit()
        await db.refresh(result)
        
        logger.info(f"Deals created successfully with id: {result.id}")
        return result
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as e:
        await db.rollback()
        logger.error(f"Validation error creating deals: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating deals: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/{id}/finalize", response_model=DealFinalizeResponse)
async def finalize_deal_handoff(
    id: int,
    data: DealFinalizeRequest,
    current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    """Complete post-deal records safely; the same request can be retried."""
    async with deal_finalize_lock(id):
        return await _finalize_deal_handoff_unlocked(id, data, current_user, db)


async def _finalize_deal_handoff_unlocked(
    id: int,
    data: DealFinalizeRequest,
    current_user: UserResponse,
    db: AsyncSession,
):
    board_permission_error: Optional[HTTPException] = None
    if data.create_service_board:
        try:
            await require_service_board_access(db, current_user, "task_create")
        except HTTPException as exc:
            board_permission_error = exc
            # Permission lookup may have opened a read transaction. End it
            # before starting the core subscription/customer transaction.
            await db.rollback()

    try:
        deal = await load_deal_for_finalize(db, id)
        subscription_step, customer_step = await finalize_subscription_and_customer(
            db,
            deal,
            ensure_subscription=data.ensure_subscription,
            auto_renew=data.auto_renew,
        )
        await db.commit()
    except HTTPException as exc:
        await db.rollback()
        if exc.status_code == 404:
            raise
        message = str(exc.detail)
        steps = {
            "subscription": _failed_finalize_step(message),
            "customer": _failed_finalize_step("订阅与客户状态属于同一事务，本次均未写入"),
            "service_board": (
                _failed_finalize_step("请先完成订阅与客户状态后再重试服务看板")
                if data.create_service_board
                else {
                    "status": "skipped",
                    "message": "本次不生成服务看板",
                    "resource_id": None,
                    "created_count": 0,
                    "retryable": False,
                }
            ),
        }
        return DealFinalizeResponse(deal_id=id, complete=False, retryable=True, steps=steps)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to finalize deal %s core records: %s", id, exc, exc_info=True)
        steps = {
            "subscription": _failed_finalize_step("订阅未完成，请重试"),
            "customer": _failed_finalize_step("客户成交状态未完成，请重试"),
            "service_board": (
                _failed_finalize_step("请先完成订阅与客户状态后再重试服务看板")
                if data.create_service_board
                else {
                    "status": "skipped",
                    "message": "本次不生成服务看板",
                    "resource_id": None,
                    "created_count": 0,
                    "retryable": False,
                }
            ),
        }
        return DealFinalizeResponse(deal_id=id, complete=False, retryable=True, steps=steps)

    if not data.create_service_board:
        board_step = {
            "status": "skipped",
            "message": "本次不生成服务看板",
            "resource_id": None,
            "created_count": 0,
            "retryable": False,
        }
    elif board_permission_error is not None:
        board_step = _failed_finalize_step(
            str(board_permission_error.detail),
            retryable=False,
        )
    else:
        try:
            deal = await load_deal_for_finalize(db, id)
            board_step = await ensure_service_board(
                db,
                deal,
                actor_id=str(current_user.id),
                actor_name=current_user.name or current_user.email or "系统管理员",
            )
            await db.commit()
        except HTTPException as exc:
            await db.rollback()
            board_step = _failed_finalize_step(str(exc.detail), retryable=True)
        except Exception as exc:
            await db.rollback()
            logger.error("Failed to finalize deal %s service board: %s", id, exc, exc_info=True)
            board_step = _failed_finalize_step("服务看板未完成，请重试", retryable=True)

    steps = {
        "subscription": subscription_step,
        "customer": customer_step,
        "service_board": board_step,
    }
    complete = all(step["status"] != "failed" for step in steps.values())
    return DealFinalizeResponse(
        deal_id=id,
        complete=complete,
        retryable=any(step.get("retryable", False) for step in steps.values()),
        steps=steps,
    )


@router.post("/batch", response_model=List[DealsResponse], status_code=201)
async def create_dealss_batch(
    request: DealsBatchCreateRequest,
    _finance_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple dealss in a single request"""
    logger.debug(f"Batch creating {len(request.items)} dealss")
    
    service = DealsService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump(), commit=False)
            if not result:
                raise HTTPException(status_code=400, detail="Failed to create deals")
            await sync_payment_from_deal(db, result, commit=False)
            results.append(result)
        await db.commit()
        for result in results:
            await db.refresh(result)
        
        logger.info(f"Batch created {len(results)} dealss successfully")
        return results
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[DealsResponse])
async def update_dealss_batch(
    request: DealsBatchUpdateRequest,
    _finance_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    """Update multiple dealss in a single request"""
    logger.debug(f"Batch updating {len(request.items)} dealss")
    
    service = DealsService(db)
    results = []
    
    try:
        if len({item.id for item in request.items}) != len(request.items):
            raise HTTPException(status_code=400, detail="Batch update contains duplicate deal IDs")
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict, commit=False)
            if not result:
                raise HTTPException(status_code=404, detail=f"Deals {item.id} not found")
            await sync_payment_from_deal(db, result, commit=False)
            results.append(result)
        await db.commit()
        for result in results:
            await db.refresh(result)
        
        logger.info(f"Batch updated {len(results)} dealss successfully")
        return results
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=DealsResponse)
async def update_deals(
    id: int,
    data: DealsUpdateData,
    _finance_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing deals"""
    logger.debug(f"Updating deals {id} with data: {data}")

    service = DealsService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict, commit=False)
        if not result:
            logger.warning(f"Deals with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Deals not found")

        await sync_payment_from_deal(db, result, commit=False)
        await db.commit()
        await db.refresh(result)
        
        logger.info(f"Deals {id} updated successfully")
        return result
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as e:
        await db.rollback()
        logger.error(f"Validation error updating deals {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating deals {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_dealss_batch(
    request: DealsBatchDeleteRequest,
    _finance_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple dealss by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} dealss")
    
    service = DealsService(db)
    deleted_count = 0
    
    try:
        if len(set(request.ids)) != len(request.ids):
            raise HTTPException(status_code=400, detail="Batch delete contains duplicate deal IDs")
        for item_id in request.ids:
            if not await service.get_by_id(item_id):
                raise HTTPException(status_code=404, detail=f"Deals {item_id} not found")
        for item_id in request.ids:
            await unlink_synced_payment_for_deal(db, item_id, commit=False)
            success = await service.delete(item_id, commit=False)
            if not success:  # Defensive: all IDs were preflighted above.
                raise HTTPException(status_code=404, detail=f"Deals {item_id} not found")
            deleted_count += 1
        await db.commit()
        
        logger.info(f"Batch deleted {deleted_count} dealss successfully")
        return {"message": f"Successfully deleted {deleted_count} dealss", "deleted_count": deleted_count}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_deals(
    id: int,
    _finance_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single deals by ID"""
    logger.debug(f"Deleting deals with id: {id}")
    
    service = DealsService(db)
    try:
        if not await service.get_by_id(id):
            logger.warning(f"Deals with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Deals not found")

        await unlink_synced_payment_for_deal(db, id, commit=False)
        success = await service.delete(id, commit=False)
        if not success:  # Defensive: the preflight lookup above already found it.
            raise HTTPException(status_code=404, detail="Deals not found")
        await db.commit()
        
        logger.info(f"Deals {id} deleted successfully")
        return {"message": "Deals deleted successfully", "id": id}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting deals {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
