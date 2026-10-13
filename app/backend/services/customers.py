import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import and_, false, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customers
from models.customer_access_grants import CustomerAccessGrant
from models.employees import Employees

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class CustomersService:
    """Service layer for Customers operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _owner_filters_for_user(scope_user: Any, employee_id: int, role: str):
        owner_filters = []
        if role not in {"sales", "sales_manager"}:
            return owner_filters
        owner_filters.append(Customers.sales_employee_id == employee_id)
        employee_name = str(getattr(scope_user, "name", "") or "").strip()
        if employee_name:
            owner_filters.append(and_(
                Customers.sales_employee_id.is_(None),
                Customers.sales_person == employee_name,
            ))
        if role == "sales_manager":
            manager_department = (
                select(Employees.department)
                .where(Employees.id == employee_id)
                .scalar_subquery()
            )
            eligible_department_members = (
                Employees.department.is_not(None),
                Employees.department == manager_department,
                Employees.status.in_(("active", "probation")),
                Employees.role.in_(("sales", "sales_manager")),
            )
            owner_filters.append(Customers.sales_employee_id.in_(
                select(Employees.id).where(*eligible_department_members)
            ))
            owner_filters.append(and_(
                Customers.sales_employee_id.is_(None),
                Customers.sales_person.in_(select(Employees.name).where(*eligible_department_members)),
            ))
        return owner_filters

    @classmethod
    def _scope_filter_for_user(cls, scope_user: Optional[Any] = None, *, write: bool = False,
                               module: str | None = None, action: str | None = None,
                               finance_level: str = "status"):
        """Explicit rules override inheritance, including denials and read-only.

        module=None selects customer shells; each linked resource separately
        checks its module. Only authenticated super_admin is unconditionally
        trusted. A missing user remains the internal, non-HTTP service contract.
        """
        if not scope_user:
            return None

        role = str(getattr(scope_user, "role", "") or "").lower()
        if role == "super_admin":
            return None
        if role == "sales_partner":
            return false()

        raw_user_id = getattr(scope_user, "id", None)
        try:
            employee_id = int(raw_user_id)
            all_grants = select(CustomerAccessGrant.customer_id).where(CustomerAccessGrant.employee_id == employee_id)
            allowed = [CustomerAccessGrant.access_level.in_(("read_only", "read_write"))]
            if write or action in {"delete", "reassign"}:
                allowed.append(CustomerAccessGrant.access_level == "read_write")
            if module == "finance":
                levels = ("none", "status", "receipts", "profit")
                if finance_level not in levels[1:]:
                    raise ValueError("Invalid finance permission level")
                allowed.append(CustomerAccessGrant.finance_access.in_(levels[levels.index(finance_level):]))
            elif module is not None:
                if module not in {"basic", "followups", "delivery", "materials"}:
                    raise ValueError("Invalid customer permission module")
                level = func.coalesce(CustomerAccessGrant.scopes[module].as_string(), CustomerAccessGrant.access_level)
                allowed.append(level == "read_write" if write else level.in_(("read_only", "read_write")))
            if action is not None:
                if action not in {"delete", "export", "reassign"}:
                    raise ValueError("Invalid customer permission action")
                allowed.append(getattr(CustomerAccessGrant, "can_" + action).is_(True))
            granted = Customers.id.in_(all_grants.where(*allowed))
            owner_filters = cls._owner_filters_for_user(scope_user, employee_id, role)
            # Ownership never grants finance, destructive actions or exports.
            if module == "finance" or action:
                owner_filters = []
            inherited = and_(~Customers.id.in_(all_grants), or_(*owner_filters)) if owner_filters else false()
            return or_(granted, inherited)
        except (TypeError, ValueError):
            return false()

    def _scope_filter(self, scope_user: Optional[Any] = None):
        return self._scope_filter_for_user(scope_user)

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

    async def get_by_id(self, obj_id: int, scope_user: Optional[Any] = None, *, write: bool = False,
                        module: str | None = None, action: str | None = None) -> Optional[Customers]:
        """Get customers by ID"""
        try:
            query = select(Customers).where(Customers.id == obj_id)
            scope_filter = self._scope_filter_for_user(scope_user, write=write, module=module, action=action)
            if scope_filter is not None:
                query = query.where(scope_filter)
            if write or action in {"delete", "reassign"}:
                query = query.with_for_update().execution_options(populate_existing=True)
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
            # A shared project may expose only a customer name, not contacts.
            # Filtering/sorting hidden basic fields must not become an oracle.
            uses_basic_fields = any(field not in {"id", "business_name"} for field in (query_dict or {}))
            uses_basic_fields = uses_basic_fields or bool(sort and sort.lstrip("-") not in {"id", "business_name"})
            if uses_basic_fields:
                basic_filter = self._scope_filter_for_user(scope_user, module="basic")
                if basic_filter is not None:
                    query = query.where(basic_filter)
                    count_query = count_query.where(basic_filter)
            
            if query_dict:
                for field, value in query_dict.items():
                    if field == "private_notes":
                        raise ValueError("Private notes cannot be used in customer list filters")
                    if hasattr(Customers, field):
                        query = query.where(getattr(Customers, field) == value)
                        count_query = count_query.where(getattr(Customers, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.lstrip("-") == "private_notes":
                    raise ValueError("Private notes cannot be used in customer list sorting")
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
            obj = await self.get_by_id(obj_id, scope_user=scope_user, write=True, module="basic")
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

    async def delete(
        self,
        obj_id: int,
        scope_user: Optional[Any] = None,
        *,
        commit: bool = True,
    ) -> bool:
        """Delete customers"""
        try:
            obj = await self.get_by_id(obj_id, scope_user=scope_user, write=True, action="delete")
            if not obj:
                logger.warning(f"Customers {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            if commit:
                await self.db.commit()
            else:
                await self.db.flush()
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
