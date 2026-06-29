import json
import logging
from datetime import datetime
from typing import List, Optional


from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services.customer_ai_copies import Customer_ai_copiesService
from services.customer_materials import Customer_materialsService
from services.operation_logs import Operation_logsService
from services.service_progresses import Service_progressesService
from services.service_tasks import Service_tasksService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/entities/service_tasks",
    tags=["service_tasks"],
    dependencies=[Depends(get_current_user)],
)


# ---------- Pydantic Schemas ----------
class Service_tasksData(BaseModel):
    """Entity data schema (for create/update)"""
    service_progress_id: Optional[int] = None
    customer_id: int
    customer_name: Optional[str] = None
    task_name: str
    task_type: Optional[str] = None
    platform: Optional[str] = None
    assignee_name: Optional[str] = None
    priority: Optional[str] = None
    status: str
    due_date: Optional[str] = None
    completed_date: Optional[str] = None
    completed_at: Optional[str] = None
    completed_by: Optional[str] = None
    selected_copy_id: Optional[int] = None
    selected_copy_title: Optional[str] = None
    selected_material_id: Optional[int] = None
    selected_material_title: Optional[str] = None
    completion_quality: Optional[str] = None
    completion_note: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None


class Service_tasksUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    service_progress_id: Optional[int] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    task_name: Optional[str] = None
    task_type: Optional[str] = None
    platform: Optional[str] = None
    assignee_name: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[str] = None
    completed_date: Optional[str] = None
    completed_at: Optional[str] = None
    completed_by: Optional[str] = None
    selected_copy_id: Optional[int] = None
    selected_copy_title: Optional[str] = None
    selected_material_id: Optional[int] = None
    selected_material_title: Optional[str] = None
    completion_quality: Optional[str] = None
    completion_note: Optional[str] = None
    notes: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[str] = None


class Service_tasksResponse(BaseModel):
    """Entity response schema"""
    id: int
    service_progress_id: Optional[int] = None
    customer_id: int
    customer_name: Optional[str] = None
    task_name: str
    task_type: Optional[str] = None
    platform: Optional[str] = None
    assignee_name: Optional[str] = None
    priority: Optional[str] = None
    status: str
    due_date: Optional[str] = None
    completed_date: Optional[str] = None
    completed_at: Optional[str] = None
    completed_by: Optional[str] = None
    selected_copy_id: Optional[int] = None
    selected_copy_title: Optional[str] = None
    selected_material_id: Optional[int] = None
    selected_material_title: Optional[str] = None
    completion_quality: Optional[str] = None
    completion_note: Optional[str] = None
    notes: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class Service_tasksListResponse(BaseModel):
    """List response schema"""
    items: List[Service_tasksResponse]
    total: int
    skip: int
    limit: int


class Service_tasksBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[Service_tasksData]


class Service_tasksBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: Service_tasksUpdateData


class Service_tasksBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[Service_tasksBatchUpdateItem]


class Service_tasksBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


class ServiceTaskCompleteRequest(BaseModel):
    """Complete a service task with lightweight operations supervision metadata."""
    platform: Optional[str] = None
    selected_copy_id: Optional[int] = None
    selected_material_id: Optional[int] = None
    completion_note: Optional[str] = None


def _operator_name(current_user: UserResponse) -> str:
    for field_name in ("name", "full_name", "email"):
        value = getattr(current_user, field_name, None)
        if value:
            return str(value)
    return "系统管理员"


SERVICE_STAGE_PROGRESS = {
    "deal_handover": 10,
    "group_created": 15,
    "collecting_materials": 20,
    "account_setup": 40,
    "content_prep": 60,
    "normal_ops": 80,
}

SERVICE_STAGE_ORDER = {
    stage: index for index, stage in enumerate(SERVICE_STAGE_PROGRESS.keys())
}

CONTENT_REFERENCE_REQUIRED_TYPES = {"publish_content", "reply_comments", "submit_report"}


def _infer_stage_from_completed_task(task) -> Optional[str]:
    task_type = (getattr(task, "task_type", "") or "").strip()
    task_text = f"{getattr(task, 'task_name', '') or ''} {getattr(task, 'notes', '') or ''}".lower()

    if task_type == "setup_group" or "服务群" in task_text or "拉群" in task_text or "建群" in task_text:
        return "group_created"
    if task_type in {"confirm_service", "collect_info", "collect_images", "collect_logo"} or "运营说明" in task_text or "素材清单" in task_text:
        return "collecting_materials"
    if task_type in {"bind_google", "open_facebook", "open_instagram"} or "权限" in task_text or "账号" in task_text:
        return "account_setup"
    if task_type in {"update_info", "collect_menu", "collect_price", "input_menu"} or "基础信息" in task_text or "资料完善" in task_text:
        return "content_prep"
    if task_type in {"publish_content", "go_live"} or "正式运营启动" in task_text:
        return "normal_ops"
    return None


def _should_advance_stage(current_stage: Optional[str], next_stage: Optional[str]) -> bool:
    if not next_stage:
        return False
    if not current_stage:
        return True
    current_order = SERVICE_STAGE_ORDER.get(current_stage, -1)
    next_order = SERVICE_STAGE_ORDER.get(next_stage, -1)
    return next_order > current_order


# ---------- Routes ----------
@router.get("", response_model=Service_tasksListResponse)
async def query_service_taskss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Query service_taskss with filtering, sorting, and pagination"""
    logger.debug(f"Querying service_taskss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = Service_tasksService(db)
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
        logger.debug(f"Found {result['total']} service_taskss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying service_taskss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=Service_tasksListResponse)
async def query_service_taskss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    # Query service_taskss with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying service_taskss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = Service_tasksService(db)
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
        logger.debug(f"Found {result['total']} service_taskss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying service_taskss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=Service_tasksResponse)
async def get_service_tasks(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Get a single service_tasks by ID"""
    logger.debug(f"Fetching service_tasks with id: {id}, fields={fields}")
    
    service = Service_tasksService(db)
    try:
        result = await service.get_by_id(id)
        if not result:
            logger.warning(f"Service_tasks with id {id} not found")
            raise HTTPException(status_code=404, detail="Service_tasks not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching service_tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=Service_tasksResponse, status_code=201)
async def create_service_tasks(
    data: Service_tasksData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new service_tasks"""
    logger.debug(f"Creating new service_tasks with data: {data}")
    
    service = Service_tasksService(db)
    try:
        result = await service.create(data.model_dump(), user_id=str(current_user.id))
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create service_tasks")
        
        logger.info(f"Service_tasks created successfully with id: {result.id}")
        return result
    except ValueError as e:
        logger.error(f"Validation error creating service_tasks: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating service_tasks: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[Service_tasksResponse], status_code=201)
async def create_service_taskss_batch(
    request: Service_tasksBatchCreateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple service_taskss in a single request"""
    logger.debug(f"Batch creating {len(request.items)} service_taskss")
    
    service = Service_tasksService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump(), user_id=str(current_user.id))
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} service_taskss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[Service_tasksResponse])
async def update_service_taskss_batch(
    request: Service_tasksBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update multiple service_taskss in a single request"""
    logger.debug(f"Batch updating {len(request.items)} service_taskss")
    
    service = Service_tasksService(db)
    results = []
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} service_taskss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.post("/{id}/complete", response_model=Service_tasksResponse)
async def complete_service_task(
    id: int,
    data: ServiceTaskCompleteRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Complete a task and record lightweight operations-quality metadata."""
    service = Service_tasksService(db)
    task = await service.get_by_id(id)
    if not task:
        raise HTTPException(status_code=404, detail="Service_tasks not found")

    copy_title = None
    material_title = None
    selected_copy = None
    selected_material = None

    if data.selected_copy_id:
        selected_copy = await Customer_ai_copiesService(db).get_by_id(data.selected_copy_id)
        if not selected_copy or selected_copy.customer_id != task.customer_id:
            raise HTTPException(status_code=400, detail="选择的文案不属于当前客户")
        copy_title = selected_copy.title or f"文案 #{selected_copy.id}"

    if data.selected_material_id:
        selected_material = await Customer_materialsService(db).get_by_id(data.selected_material_id)
        if not selected_material or selected_material.customer_id != task.customer_id:
            raise HTTPException(status_code=400, detail="选择的素材不属于当前客户")
        material_title = selected_material.title or selected_material.file_name or f"素材 #{selected_material.id}"

    now = datetime.utcnow()
    now_iso = now.isoformat()
    operator = _operator_name(current_user)
    has_reference = bool(selected_copy or selected_material)
    reference_required = (task.task_type or "") in CONTENT_REFERENCE_REQUIRED_TYPES
    quality = "standard" if has_reference or not reference_required else "low_quality"
    platform = (data.platform or "").strip() or getattr(selected_material, "platform", None) or getattr(selected_copy, "platform", None) or None

    update_dict = {
        "status": "completed",
        "platform": platform,
        "completed_date": now.date().isoformat(),
        "completed_at": now_iso,
        "completed_by": operator,
        "selected_copy_id": data.selected_copy_id,
        "selected_copy_title": copy_title,
        "selected_material_id": data.selected_material_id,
        "selected_material_title": material_title,
        "completion_quality": quality,
        "completion_note": (data.completion_note or "").strip() or None,
    }

    try:
        result = await service.update(id, update_dict)
    except Exception as e:
        logger.error(f"Error completing service_tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    # Best-effort side effects: mark the selected copy/material as used and write an audit log.
    try:
        if selected_copy:
            await Customer_ai_copiesService(db).update(selected_copy.id, {"status": "used", "updated_at": now})
        if selected_material:
            await Customer_materialsService(db).update(
                selected_material.id,
                {"usage_status": "used", "used_at": now, "updated_at": now},
            )
        if task.service_progress_id:
            progress_service = Service_progressesService(db)
            progress = await progress_service.get_by_id(task.service_progress_id)
            next_stage = _infer_stage_from_completed_task(task)
            summary_parts = [f"完成任务：{task.task_name}"]
            if platform:
                summary_parts.append(f"平台：{platform}")
            if copy_title:
                summary_parts.append(f"使用文案：{copy_title}")
            if material_title:
                summary_parts.append(f"使用素材：{material_title}")
            if quality == "low_quality":
                summary_parts.append("未选择文案/素材，低质量完成")
            progress_update = {
                "last_update_time": now_iso,
                "last_update_person": operator,
                "last_work_summary": "；".join(summary_parts),
            }
            if progress and _should_advance_stage(getattr(progress, "service_stage", None), next_stage):
                progress_update["service_stage"] = next_stage
                progress_update["progress_percent"] = SERVICE_STAGE_PROGRESS.get(
                    next_stage,
                    getattr(progress, "progress_percent", None) or 10,
                )
            await progress_service.update(task.service_progress_id, progress_update)
    except Exception:
        logger.warning("Completed task %s but failed to sync related usage/progress metadata", id, exc_info=True)

    try:
        references = []
        if platform:
            references.append(f"平台: {platform}")
        if copy_title:
            references.append(f"文案: {copy_title}")
        if material_title:
            references.append(f"素材: {material_title}")
        reference_text = "；".join(references) if references else "未选择文案或素材，系统标记为低质量完成"
        await Operation_logsService(db).create(
            {
                "customer_id": task.customer_id,
                "action_type": "complete_service_task",
                "action_detail": f"完成服务任务「{task.task_name}」；{reference_text}",
                "operator_name": operator,
                "created_at": now,
            },
            user_id=str(current_user.id),
        )
    except Exception:
        logger.warning("Completed task %s but failed to create operation log", id, exc_info=True)

    if not result:
        raise HTTPException(status_code=404, detail="Service_tasks not found")
    return result


@router.put("/{id}", response_model=Service_tasksResponse)
async def update_service_tasks(
    id: int,
    data: Service_tasksUpdateData,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing service_tasks"""
    logger.debug(f"Updating service_tasks {id} with data: {data}")

    service = Service_tasksService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict)
        if not result:
            logger.warning(f"Service_tasks with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Service_tasks not found")
        
        logger.info(f"Service_tasks {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating service_tasks {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating service_tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_service_taskss_batch(
    request: Service_tasksBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple service_taskss by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} service_taskss")
    
    service = Service_tasksService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} service_taskss successfully")
        return {"message": f"Successfully deleted {deleted_count} service_taskss", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_service_tasks(
    id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single service_tasks by ID"""
    logger.debug(f"Deleting service_tasks with id: {id}")
    
    service = Service_tasksService(db)
    try:
        success = await service.delete(id)
        if not success:
            logger.warning(f"Service_tasks with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Service_tasks not found")
        
        logger.info(f"Service_tasks {id} deleted successfully")
        return {"message": "Service_tasks deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting service_tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
