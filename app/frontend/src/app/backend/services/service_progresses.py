import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.service_progresses import Service_progresses

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class Service_progressesService:
    """Service layer for Service_progresses operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> Optional[Service_progresses]:
        """Create a new service_progresses"""
        try:
            obj = Service_progresses(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created service_progresses with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating service_progresses: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int) -> Optional[Service_progresses]:
        """Get service_progresses by ID"""
        try:
            query = select(Service_progresses).where(Service_progresses.id == obj_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching service_progresses {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of service_progressess"""
        try:
            query = select(Service_progresses)
            count_query = select(func.count(Service_progresses.id))
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Service_progresses, field):
                        query = query.where(getattr(Service_progresses, field) == value)
                        count_query = count_query.where(getattr(Service_progresses, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Service_progresses, field_name):
                        query = query.order_by(getattr(Service_progresses, field_name).desc())
                else:
                    if hasattr(Service_progresses, sort):
                        query = query.order_by(getattr(Service_progresses, sort))
            else:
                query = query.order_by(Service_progresses.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching service_progresses list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Service_progresses]:
        """Update service_progresses"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Service_progresses {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated service_progresses {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating service_progresses {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int) -> bool:
        """Delete service_progresses"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Service_progresses {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted service_progresses {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting service_progresses {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Service_progresses]:
        """Get service_progresses by any field"""
        try:
            if not hasattr(Service_progresses, field_name):
                raise ValueError(f"Field {field_name} does not exist on Service_progresses")
            result = await self.db.execute(
                select(Service_progresses).where(getattr(Service_progresses, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching service_progresses by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Service_progresses]:
        """Get list of service_progressess filtered by field"""
        try:
            if not hasattr(Service_progresses, field_name):
                raise ValueError(f"Field {field_name} does not exist on Service_progresses")
            result = await self.db.execute(
                select(Service_progresses)
                .where(getattr(Service_progresses, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Service_progresses.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching service_progressess by {field_name}: {str(e)}")
            raise