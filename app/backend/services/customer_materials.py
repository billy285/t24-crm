import logging
from typing import Any, Dict, List, Optional

from models.customer_materials import Customer_materials
from sqlalchemy import func, select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from services.customer_scope import apply_customer_scope, ensure_customer_access
from services.customers import CustomersService

from services.customer_record_audit import record_customer_change

logger = logging.getLogger(__name__)


def apply_material_visibility(statement, scope_user):
    """Content sharing does not implicitly share owner or financial attachments."""
    if scope_user is None or str(getattr(scope_user, "role", "")).strip().lower() == "super_admin":
        return statement
    finance_scope = CustomersService._scope_filter_for_user(scope_user, module="finance", finance_level="receipts")
    return statement.where(or_(
        Customer_materials.visibility == "team",
        and_(Customer_materials.visibility == "finance", finance_scope),
    ))


class Customer_materialsService:
    """Service layer for customer material records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any], user_id: Optional[str] = None) -> Customer_materials:
        try:
            if user_id:
                data["user_id"] = user_id
            obj = Customer_materials(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            return obj
        except Exception:
            await self.db.rollback()
            logger.exception("Error creating customer material")
            raise

    async def get_by_id(self, obj_id: int, user_id: Optional[str] = None, scope_user: Optional[Any] = None) -> Optional[Customer_materials]:
        query = apply_customer_scope(select(Customer_materials).where(Customer_materials.id == obj_id), Customer_materials, scope_user)
        query = apply_material_visibility(query, scope_user)
        if user_id:
            query = query.where(Customer_materials.user_id == user_id)
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
        query = select(Customer_materials)
        count_query = select(func.count(Customer_materials.id))
        query = apply_customer_scope(query, Customer_materials, scope_user)
        count_query = apply_customer_scope(count_query, Customer_materials, scope_user)
        query = apply_material_visibility(query, scope_user)
        count_query = apply_material_visibility(count_query, scope_user)

        if user_id:
            query = query.where(Customer_materials.user_id == user_id)
            count_query = count_query.where(Customer_materials.user_id == user_id)

        if query_dict:
            for field, value in query_dict.items():
                if value in (None, ""):
                    continue
                if hasattr(Customer_materials, field):
                    query = query.where(getattr(Customer_materials, field) == value)
                    count_query = count_query.where(getattr(Customer_materials, field) == value)

        total = (await self.db.execute(count_query)).scalar() or 0

        if sort:
            if sort.startswith("-"):
                field_name = sort[1:]
                if hasattr(Customer_materials, field_name):
                    query = query.order_by(getattr(Customer_materials, field_name).desc())
            elif hasattr(Customer_materials, sort):
                query = query.order_by(getattr(Customer_materials, sort))
        else:
            query = query.order_by(Customer_materials.id.desc())

        result = await self.db.execute(query.offset(skip).limit(limit))
        return {"items": result.scalars().all(), "total": total, "skip": skip, "limit": limit}

    async def update(self, obj_id: int, update_data: Dict[str, Any], user_id: Optional[str] = None, scope_user: Optional[Any] = None) -> Optional[Customer_materials]:
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
            logger.exception("Error updating customer material %s", obj_id)
            raise

    async def delete(self, obj_id: int, user_id: Optional[str] = None, scope_user: Optional[Any] = None) -> Optional[Customer_materials]:
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
            logger.exception("Error deleting customer material %s", obj_id)
            raise

    async def list_by_field(
        self,
        field_name: str,
        field_value: Any,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Customer_materials]:
        if not hasattr(Customer_materials, field_name):
            raise ValueError(f"Field {field_name} does not exist on Customer_materials")
        result = await self.db.execute(
            select(Customer_materials)
            .where(getattr(Customer_materials, field_name) == field_value)
            .offset(skip)
            .limit(limit)
            .order_by(Customer_materials.id.desc())
        )
        return result.scalars().all()
