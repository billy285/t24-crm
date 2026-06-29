import logging
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.customer_ai_copies import Customer_ai_copies

logger = logging.getLogger(__name__)


class Customer_ai_copiesService:
    """Service layer for saved customer AI copy drafts."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any], user_id: Optional[str] = None) -> Customer_ai_copies:
        try:
            if user_id:
                data["user_id"] = user_id
            obj = Customer_ai_copies(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error("Error creating customer_ai_copies: %s", e)
            raise

    async def get_by_id(self, obj_id: int) -> Optional[Customer_ai_copies]:
        result = await self.db.execute(select(Customer_ai_copies).where(Customer_ai_copies.id == obj_id))
        return result.scalar_one_or_none()

    async def get_list(
        self,
        skip: int = 0,
        limit: int = 50,
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = select(Customer_ai_copies)
        count_query = select(func.count(Customer_ai_copies.id))

        if query_dict:
            for field, value in query_dict.items():
                if hasattr(Customer_ai_copies, field):
                    query = query.where(getattr(Customer_ai_copies, field) == value)
                    count_query = count_query.where(getattr(Customer_ai_copies, field) == value)

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        if sort:
            if sort.startswith("-"):
                field_name = sort[1:]
                if hasattr(Customer_ai_copies, field_name):
                    query = query.order_by(getattr(Customer_ai_copies, field_name).desc())
            elif hasattr(Customer_ai_copies, sort):
                query = query.order_by(getattr(Customer_ai_copies, sort))
        else:
            query = query.order_by(Customer_ai_copies.id.desc())

        result = await self.db.execute(query.offset(skip).limit(limit))
        return {"items": result.scalars().all(), "total": total, "skip": skip, "limit": limit}

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Customer_ai_copies]:
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                return None
            for key, value in update_data.items():
                if hasattr(obj, key) and key != "user_id":
                    setattr(obj, key, value)
            await self.db.commit()
            await self.db.refresh(obj)
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error("Error updating customer_ai_copies %s: %s", obj_id, e)
            raise

    async def delete(self, obj_id: int) -> bool:
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                return False
            await self.db.delete(obj)
            await self.db.commit()
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error("Error deleting customer_ai_copies %s: %s", obj_id, e)
            raise
