import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.employees import Employees

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class EmployeesService:
    """Service layer for Employees operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> Optional[Employees]:
        """Create a new employees"""
        try:
            obj = Employees(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created employees with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating employees: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int) -> Optional[Employees]:
        """Get employees by ID"""
        try:
            query = select(Employees).where(Employees.id == obj_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching employees {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of employeess"""
        try:
            query = select(Employees)
            count_query = select(func.count(Employees.id))
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Employees, field):
                        query = query.where(getattr(Employees, field) == value)
                        count_query = count_query.where(getattr(Employees, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Employees, field_name):
                        query = query.order_by(getattr(Employees, field_name).desc())
                else:
                    if hasattr(Employees, sort):
                        query = query.order_by(getattr(Employees, sort))
            else:
                query = query.order_by(Employees.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching employees list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Employees]:
        """Update employees"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Employees {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated employees {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating employees {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int) -> bool:
        """Delete employees"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Employees {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted employees {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting employees {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Employees]:
        """Get employees by any field"""
        try:
            if not hasattr(Employees, field_name):
                raise ValueError(f"Field {field_name} does not exist on Employees")
            result = await self.db.execute(
                select(Employees).where(getattr(Employees, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching employees by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Employees]:
        """Get list of employeess filtered by field"""
        try:
            if not hasattr(Employees, field_name):
                raise ValueError(f"Field {field_name} does not exist on Employees")
            result = await self.db.execute(
                select(Employees)
                .where(getattr(Employees, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Employees.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching employeess by {field_name}: {str(e)}")
            raise