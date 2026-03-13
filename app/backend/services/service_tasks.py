import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.service_tasks import Service_tasks

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class Service_tasksService:
    """Service layer for Service_tasks operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any], user_id: Optional[str] = None) -> Optional[Service_tasks]:
        """Create a new service_tasks"""
        try:
            if user_id:
                data['user_id'] = user_id
            obj = Service_tasks(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created service_tasks with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating service_tasks: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int) -> Optional[Service_tasks]:
        """Get service_tasks by ID"""
        try:
            query = select(Service_tasks).where(Service_tasks.id == obj_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching service_tasks {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of service_taskss"""
        try:
            query = select(Service_tasks)
            count_query = select(func.count(Service_tasks.id))
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Service_tasks, field):
                        query = query.where(getattr(Service_tasks, field) == value)
                        count_query = count_query.where(getattr(Service_tasks, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Service_tasks, field_name):
                        query = query.order_by(getattr(Service_tasks, field_name).desc())
                else:
                    if hasattr(Service_tasks, sort):
                        query = query.order_by(getattr(Service_tasks, sort))
            else:
                query = query.order_by(Service_tasks.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching service_tasks list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Service_tasks]:
        """Update service_tasks"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Service_tasks {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated service_tasks {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating service_tasks {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int) -> bool:
        """Delete service_tasks"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Service_tasks {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted service_tasks {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting service_tasks {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Service_tasks]:
        """Get service_tasks by any field"""
        try:
            if not hasattr(Service_tasks, field_name):
                raise ValueError(f"Field {field_name} does not exist on Service_tasks")
            result = await self.db.execute(
                select(Service_tasks).where(getattr(Service_tasks, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching service_tasks by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Service_tasks]:
        """Get list of service_taskss filtered by field"""
        try:
            if not hasattr(Service_tasks, field_name):
                raise ValueError(f"Field {field_name} does not exist on Service_tasks")
            result = await self.db.execute(
                select(Service_tasks)
                .where(getattr(Service_tasks, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Service_tasks.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching service_taskss by {field_name}: {str(e)}")
            raise