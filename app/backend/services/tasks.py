import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import HTTPException
from sqlalchemy import false, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.tasks import Tasks
from models.automation import DataQualityIssue
from models.company_roadmap import StrategyRecommendationDecision

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class TasksService:
    """Service layer for Tasks operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> Optional[Tasks]:
        """Create a new tasks"""
        try:
            obj = Tasks(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created tasks with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating tasks: {str(e)}")
            raise

    @staticmethod
    def _visibility_conditions(
        employee_ids: Optional[List[int]],
        employee_names: Optional[List[str]],
    ) -> List[Any]:
        """Build the assignee/collaborator visibility predicate used by every read path."""
        conditions: List[Any] = []
        safe_ids = sorted({int(item) for item in (employee_ids or []) if item is not None})
        safe_names = sorted({str(item).strip() for item in (employee_names or []) if str(item).strip()})

        if safe_ids:
            conditions.append(Tasks.assignee_id.in_(safe_ids))
        if safe_names:
            conditions.append(Tasks.assignee_name.in_(safe_names))

            # Frontend values are stored as comma-delimited names. Normalize the
            # Chinese comma and the standard ", " separator before matching a
            # complete token so "Ann" cannot see tasks assigned to "Anna".
            normalized_collaborators = func.replace(
                func.replace(func.coalesce(Tasks.collaborator_names, ""), "，", ","),
                ", ",
                ",",
            )
            wrapped_collaborators = literal(",") + normalized_collaborators + literal(",")
            for name in safe_names:
                escaped_name = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                conditions.append(
                    wrapped_collaborators.like(f"%,{escaped_name},%", escape="\\")
                )

        return conditions

    @classmethod
    def _apply_visibility_scope(
        cls,
        query,
        *,
        unrestricted: bool,
        employee_ids: Optional[List[int]],
        employee_names: Optional[List[str]],
    ):
        if unrestricted:
            return query
        conditions = cls._visibility_conditions(employee_ids, employee_names)
        return query.where(or_(*conditions)) if conditions else query.where(false())

    async def get_by_id(
        self,
        obj_id: int,
        *,
        unrestricted: bool = True,
        employee_ids: Optional[List[int]] = None,
        employee_names: Optional[List[str]] = None,
    ) -> Optional[Tasks]:
        """Get tasks by ID"""
        try:
            query = select(Tasks).where(Tasks.id == obj_id)
            query = self._apply_visibility_scope(
                query,
                unrestricted=unrestricted,
                employee_ids=employee_ids,
                employee_names=employee_names,
            )
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching tasks {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
        unrestricted: bool = True,
        employee_ids: Optional[List[int]] = None,
        employee_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of taskss"""
        try:
            query = select(Tasks)
            count_query = select(func.count(Tasks.id))

            query = self._apply_visibility_scope(
                query,
                unrestricted=unrestricted,
                employee_ids=employee_ids,
                employee_names=employee_names,
            )
            count_query = self._apply_visibility_scope(
                count_query,
                unrestricted=unrestricted,
                employee_ids=employee_ids,
                employee_names=employee_names,
            )
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Tasks, field):
                        query = query.where(getattr(Tasks, field) == value)
                        count_query = count_query.where(getattr(Tasks, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Tasks, field_name):
                        query = query.order_by(getattr(Tasks, field_name).desc())
                else:
                    if hasattr(Tasks, sort):
                        query = query.order_by(getattr(Tasks, sort))
            else:
                query = query.order_by(Tasks.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching tasks list: {str(e)}")
            raise

    async def update(
        self,
        obj_id: int,
        update_data: Dict[str, Any],
        *,
        unrestricted: bool = True,
        employee_ids: Optional[List[int]] = None,
        employee_names: Optional[List[str]] = None,
    ) -> Optional[Tasks]:
        """Update tasks"""
        try:
            obj = await self.get_by_id(
                obj_id,
                unrestricted=unrestricted,
                employee_ids=employee_ids,
                employee_names=employee_names,
            )
            if not obj:
                logger.warning(f"Tasks {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            next_status = update_data.get("status")
            now = datetime.now(timezone.utc)
            if next_status == "completed":
                completion_result = str(
                    update_data.get("completion_result") or obj.completion_result or ""
                ).strip()
                if obj.automation_issue_id and not completion_result:
                    raise ValueError("系统任务完成时必须填写处理结果")
                obj.completion_result = completion_result or obj.completion_result
                obj.completed_at = now
            elif next_status:
                obj.completed_at = None

            if obj.automation_issue_id and next_status:
                issue = (await self.db.execute(
                    select(DataQualityIssue).where(DataQualityIssue.id == obj.automation_issue_id)
                )).scalar_one_or_none()
                if issue:
                    if next_status == "completed":
                        issue.status = "resolved"
                        issue.resolved_at = now
                        issue.resolution_note = obj.completion_result
                    elif next_status == "cancelled":
                        issue.status = "resolved"
                        issue.resolved_at = now
                        issue.resolution_note = obj.completion_result or "任务已取消，由管理员人工复核"
                    elif next_status == "pending":
                        issue.status = "open"
                        issue.resolved_at = None
                        issue.resolution_note = None
                    else:
                        issue.status = "in_progress"
                        issue.resolved_at = None
                        issue.resolution_note = None

            if next_status:
                decision = (
                    await self.db.execute(
                        select(StrategyRecommendationDecision).where(
                            StrategyRecommendationDecision.task_id == obj.id
                        )
                    )
                ).scalar_one_or_none()
                if decision:
                    if next_status == "completed":
                        if not str(obj.completion_result or "").strip():
                            raise ValueError("公司里程碑任务完成时必须填写处理结果")
                        decision.status = "completed"
                    elif next_status == "cancelled":
                        decision.status = "deferred"
                    elif next_status in {"pending", "in_progress"} and decision.status != "accepted":
                        decision.status = "accepted"

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated tasks {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating tasks {obj_id}: {str(e)}")
            raise

    async def delete(
        self,
        obj_id: int,
        *,
        unrestricted: bool = True,
        employee_ids: Optional[List[int]] = None,
        employee_names: Optional[List[str]] = None,
    ) -> bool:
        """Delete tasks"""
        try:
            obj = await self.get_by_id(
                obj_id,
                unrestricted=unrestricted,
                employee_ids=employee_ids,
                employee_names=employee_names,
            )
            if not obj:
                logger.warning(f"Tasks {obj_id} not found for deletion")
                return False
            if obj.automation_issue_id:
                raise ValueError("系统自动任务属于数据质量闭环，不能删除；可以完成并填写处理结果")
            if obj.opportunity_id:
                raise ValueError("商机跟进任务属于商机闭环，不能单独删除；请在商机中成交或关闭")
            roadmap_decision = (
                await self.db.execute(
                    select(StrategyRecommendationDecision.id).where(
                        StrategyRecommendationDecision.task_id == obj.id
                    )
                )
            ).scalar_one_or_none()
            if roadmap_decision is not None:
                raise HTTPException(
                    status_code=409,
                    detail="公司里程碑任务属于经营决策闭环，不能直接删除；请先在公司战略与里程碑中解除或调整决策",
                )
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted tasks {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting tasks {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Tasks]:
        """Get tasks by any field"""
        try:
            if not hasattr(Tasks, field_name):
                raise ValueError(f"Field {field_name} does not exist on Tasks")
            result = await self.db.execute(
                select(Tasks).where(getattr(Tasks, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching tasks by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Tasks]:
        """Get list of taskss filtered by field"""
        try:
            if not hasattr(Tasks, field_name):
                raise ValueError(f"Field {field_name} does not exist on Tasks")
            result = await self.db.execute(
                select(Tasks)
                .where(getattr(Tasks, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Tasks.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching taskss by {field_name}: {str(e)}")
            raise
