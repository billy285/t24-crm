"""Shared customer visibility scope for customer-linked entity queries."""

from typing import Any, Optional, Type

from sqlalchemy import false, select
from sqlalchemy.sql import Select
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customers
from services.customers import CustomersService


def apply_customer_scope(
    statement: Select,
    entity_model: Type[Any],
    scope_user: Optional[Any],
) -> Select:
    """Restrict a customer-linked entity statement to customers visible to a user."""
    scope_filter = CustomersService._scope_filter_for_user(scope_user)
    if scope_filter is None:
        return statement
    return statement.join(Customers, entity_model.customer_id == Customers.id).where(scope_filter)


async def ensure_customer_access(db: AsyncSession, scope_user: Any, customer_id: int) -> Customers:
    """Return the visible customer or fail without revealing whether it exists."""
    customer = await CustomersService(db).get_by_id(int(customer_id), scope_user=scope_user)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def callback_customer_scope_filter(scope_user: Any):
    """Reuse the customer source-of-truth scope with callback role hardening."""
    role = str(getattr(scope_user, "role", "") or "").strip().lower()
    role = {"operations": "ops", "operation": "ops"}.get(role, role)
    if role in {"admin", "super_admin"}:
        return None
    if role not in {"ops", "sales", "sales_manager"}:
        return false()
    return CustomersService._scope_filter_for_user(scope_user)


def apply_callback_customer_scope(statement: Select, entity_model: Type[Any], scope_user: Any) -> Select:
    scope_filter = callback_customer_scope_filter(scope_user)
    if scope_filter is None:
        return statement
    return statement.join(Customers, entity_model.customer_id == Customers.id).where(scope_filter)


async def ensure_callback_customer_access(db: AsyncSession, scope_user: Any, customer_id: int) -> Customers:
    statement = select(Customers).where(Customers.id == int(customer_id))
    scope_filter = callback_customer_scope_filter(scope_user)
    if scope_filter is not None:
        statement = statement.where(scope_filter)
    customer = (await db.execute(statement)).scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer
