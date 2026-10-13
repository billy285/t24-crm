"""Least-privilege customer fields used by shared content tools."""
from types import SimpleNamespace
from services.customer_permissions import get_customer_permissions


async def customer_for_content(db, customer, user):
    if user is None:
        return customer
    permissions = await get_customer_permissions(db, user, customer.id)
    if permissions.get("modules", {}).get("basic", {}).get("read"):
        return customer
    # A materials grant exposes the customer shell, not its basic notes/details.
    return SimpleNamespace(id=customer.id, business_name=customer.business_name)
