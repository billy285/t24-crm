import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.follow_ups import Follow_ups

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class Follow_upsService:
    """Service layer for Follow_ups operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> Optional[Follow_ups]:
        """Create a new follow_ups"""
        try:
            obj = Follow_ups(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created follow_ups with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating follow_ups: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int) -> Optional[Follow_ups]:
        """Get follow_ups by ID"""
        try:
            query = select(Follow_ups).where(Follow_ups.id == obj_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching follow_ups {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of follow_upss"""
        try:
            query = select(Follow_ups)
            count_query = select(func.count(Follow_ups.id))
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Follow_ups, field):
                        query = query.where(getattr(Follow_ups, field) == value)
                        count_query = count_query.where(getattr(Follow_ups, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Follow_ups, field_name):
                        query = query.order_by(getattr(Follow_ups, field_name).desc())
                else:
                    if hasattr(Follow_ups, sort):
                        query = query.order_by(getattr(Follow_ups, sort))
            else:
                query = query.order_by(Follow_ups.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching follow_ups list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Follow_ups]:
        """Update follow_ups"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Follow_ups {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated follow_ups {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating follow_ups {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int) -> bool:
        """Delete follow_ups"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Follow_ups {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted follow_ups {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting follow_ups {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Follow_ups]:
        """Get follow_ups by any field"""
        try:
            if not hasattr(Follow_ups, field_name):
                raise ValueError(f"Field {field_name} does not exist on Follow_ups")
            result = await self.db.execute(
                select(Follow_ups).where(getattr(Follow_ups, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching follow_ups by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Follow_ups]:
        """Get list of follow_upss filtered by field"""
        try:
            if not hasattr(Follow_ups, field_name):
                raise ValueError(f"Field {field_name} does not exist on Follow_ups")
            result = await self.db.execute(
                select(Follow_ups)
                .where(getattr(Follow_ups, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Follow_ups.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching follow_upss by {field_name}: {str(e)}")
            raise