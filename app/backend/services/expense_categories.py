import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.expense_categories import Expense_categories

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class Expense_categoriesService:
    """Service layer for Expense_categories operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> Optional[Expense_categories]:
        """Create a new expense_categories"""
        try:
            obj = Expense_categories(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created expense_categories with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating expense_categories: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int) -> Optional[Expense_categories]:
        """Get expense_categories by ID"""
        try:
            query = select(Expense_categories).where(Expense_categories.id == obj_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching expense_categories {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of expense_categoriess"""
        try:
            query = select(Expense_categories)
            count_query = select(func.count(Expense_categories.id))
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Expense_categories, field):
                        query = query.where(getattr(Expense_categories, field) == value)
                        count_query = count_query.where(getattr(Expense_categories, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Expense_categories, field_name):
                        query = query.order_by(getattr(Expense_categories, field_name).desc())
                else:
                    if hasattr(Expense_categories, sort):
                        query = query.order_by(getattr(Expense_categories, sort))
            else:
                query = query.order_by(Expense_categories.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching expense_categories list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Expense_categories]:
        """Update expense_categories"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Expense_categories {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated expense_categories {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating expense_categories {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int) -> bool:
        """Delete expense_categories"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Expense_categories {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted expense_categories {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting expense_categories {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Expense_categories]:
        """Get expense_categories by any field"""
        try:
            if not hasattr(Expense_categories, field_name):
                raise ValueError(f"Field {field_name} does not exist on Expense_categories")
            result = await self.db.execute(
                select(Expense_categories).where(getattr(Expense_categories, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching expense_categories by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Expense_categories]:
        """Get list of expense_categoriess filtered by field"""
        try:
            if not hasattr(Expense_categories, field_name):
                raise ValueError(f"Field {field_name} does not exist on Expense_categories")
            result = await self.db.execute(
                select(Expense_categories)
                .where(getattr(Expense_categories, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Expense_categories.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching expense_categoriess by {field_name}: {str(e)}")
            raise