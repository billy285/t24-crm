import logging
from typing import Any, Dict, Optional

from models.customer_menu_items import Customer_menu_items
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.customer_scope import apply_customer_scope, ensure_customer_access

from services.customer_record_audit import record_customer_change

logger = logging.getLogger(__name__)


class Customer_menu_itemsService:
    """Service layer for customer menu/service item records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any], user_id: Optional[str] = None) -> Customer_menu_items:
        try:
            if user_id:
                data["user_id"] = user_id
            obj = Customer_menu_items(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            return obj
        except Exception:
            await self.db.rollback()
            logger.exception("Error creating customer menu item")
            raise

    async def get_by_id(self, obj_id: int, user_id: Optional[str] = None, scope_user: Optional[Any] = None) -> Optional[Customer_menu_items]:
        query = apply_customer_scope(select(Customer_menu_items).where(Customer_menu_items.id == obj_id), Customer_menu_items, scope_user)
        if user_id:
            query = query.where(Customer_menu_items.user_id == user_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_list(
        self,
        skip: int = 0,
        limit: int = 50,
        user_id: Optional[str] = None,
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
        scope_user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        query = select(Customer_menu_items)
        count_query = select(func.count(Customer_menu_items.id))
        query = apply_customer_scope(query, Customer_menu_items, scope_user)
        count_query = apply_customer_scope(count_query, Customer_menu_items, scope_user)

        if user_id:
            query = query.where(Customer_menu_items.user_id == user_id)
            count_query = count_query.where(Customer_menu_items.user_id == user_id)

        if query_dict:
            for field, value in query_dict.items():
                if value in (None, ""):
                    continue
                if hasattr(Customer_menu_items, field):
                    query = query.where(getattr(Customer_menu_items, field) == value)
                    count_query = count_query.where(getattr(Customer_menu_items, field) == value)

        total = (await self.db.execute(count_query)).scalar() or 0

        if sort:
            if sort.startswith("-"):
                field_name = sort[1:]
                if hasattr(Customer_menu_items, field_name):
                    query = query.order_by(getattr(Customer_menu_items, field_name).desc())
            elif hasattr(Customer_menu_items, sort):
                query = query.order_by(getattr(Customer_menu_items, sort))
        else:
            query = query.order_by(Customer_menu_items.is_featured.desc(), Customer_menu_items.id.desc())

        result = await self.db.execute(query.offset(skip).limit(limit))
        return {"items": result.scalars().all(), "total": total, "skip": skip, "limit": limit}

    async def update(self, obj_id: int, update_data: Dict[str, Any], user_id: Optional[str] = None, scope_user: Optional[Any] = None) -> Optional[Customer_menu_items]:
        try:
            obj = await self.get_by_id(obj_id, user_id=user_id, scope_user=scope_user)
            if not obj:
                return None
            if scope_user is not None:
                await ensure_customer_access(self.db, scope_user, obj.customer_id, write=True, module="materials")
            record_customer_change(self.db, scope_user, obj, "materials", changes=update_data)
            for key, value in update_data.items():
                if hasattr(obj, key) and key != "user_id":
                    setattr(obj, key, value)
            await self.db.commit()
            await self.db.refresh(obj)
            return obj
        except Exception:
            await self.db.rollback()
            logger.exception("Error updating customer menu item %s", obj_id)
            raise

    async def delete(self, obj_id: int, user_id: Optional[str] = None, scope_user: Optional[Any] = None) -> Optional[Customer_menu_items]:
        try:
            obj = await self.get_by_id(obj_id, user_id=user_id, scope_user=scope_user)
            if not obj:
                return None
            if scope_user is not None:
                await ensure_customer_access(self.db, scope_user, obj.customer_id, write=True, module="materials", action="delete")
            record_customer_change(self.db, scope_user, obj, "materials", deleted=True)
            await self.db.delete(obj)
            await self.db.commit()
            return obj
        except Exception:
            await self.db.rollback()
            logger.exception("Error deleting customer menu item %s", obj_id)
            raise
