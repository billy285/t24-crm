import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import false, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customers

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class CustomersService:
    """Service layer for Customers operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _scope_filter(self, scope_user: Optional[Any] = None):
        """Return a customer ownership filter for non-all-data roles."""
        if not scope_user:
            return None

        role = str(getattr(scope_user, "role", "") or "").lower()
        if role in {"admin", "super_admin", "finance", "ops", "operations"}:
            return None

        conditions = []
        raw_user_id = getattr(scope_user, "id", None)
        try:
            conditions.append(Customers.sales_employee_id == int(raw_user_id))
        except (TypeError, ValueError):
            pass

        user_name = (getattr(scope_user, "name", None) or "").strip()
        if user_name:
            conditions.append(Customers.sales_person == user_name)

        return or_(*conditions) if conditions else false()

    async def create(self, data: Dict[str, Any], *, commit: bool = True) -> Optional[Customers]:
        """Create a new customers"""
        try:
            obj = Customers(**data)
            self.db.add(obj)
            if commit:
                await self.db.commit()
                await self.db.refresh(obj)
            else:
                await self.db.flush()
            logger.info(f"Created customers with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating customers: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int, scope_user: Optional[Any] = None) -> Optional[Customers]:
        """Get customers by ID"""
        try:
            query = select(Customers).where(Customers.id == obj_id)
            scope_filter = self._scope_filter(scope_user)
            if scope_filter is not None:
                query = query.where(scope_filter)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching customers {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
        scope_user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of customerss"""
        try:
            query = select(Customers)
            count_query = select(func.count(Customers.id))
            scope_filter = self._scope_filter(scope_user)
            if scope_filter is not None:
                query = query.where(scope_filter)
                count_query = count_query.where(scope_filter)
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Customers, field):
                        query = query.where(getattr(Customers, field) == value)
                        count_query = count_query.where(getattr(Customers, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Customers, field_name):
                        query = query.order_by(getattr(Customers, field_name).desc())
                else:
                    if hasattr(Customers, sort):
                        query = query.order_by(getattr(Customers, sort))
            else:
                query = query.order_by(Customers.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching customers list: {str(e)}")
            raise

    async def update(
        self, obj_id: int, update_data: Dict[str, Any], scope_user: Optional[Any] = None, *, commit: bool = True
    ) -> Optional[Customers]:
        """Update customers"""
        try:
            obj = await self.get_by_id(obj_id, scope_user=scope_user)
            if not obj:
                logger.warning(f"Customers {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            if commit:
                await self.db.commit()
                await self.db.refresh(obj)
            else:
                await self.db.flush()
            logger.info(f"Updated customers {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating customers {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int, scope_user: Optional[Any] = None) -> bool:
        """Delete customers"""
        try:
            obj = await self.get_by_id(obj_id, scope_user=scope_user)
            if not obj:
                logger.warning(f"Customers {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted customers {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting customers {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Customers]:
        """Get customers by any field"""
        try:
            if not hasattr(Customers, field_name):
                raise ValueError(f"Field {field_name} does not exist on Customers")
            result = await self.db.execute(
                select(Customers).where(getattr(Customers, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching customers by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Customers]:
        """Get list of customerss filtered by field"""
        try:
            if not hasattr(Customers, field_name):
                raise ValueError(f"Field {field_name} does not exist on Customers")
            result = await self.db.execute(
                select(Customers)
                .where(getattr(Customers, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Customers.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching customerss by {field_name}: {str(e)}")
            raise
