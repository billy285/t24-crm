import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.operation_logs import Operation_logs

logger = logging.getLogger(__name__)


ALLOWED_OPERATION_ACTION_TYPES = frozenset({
    "user_note",
    "create_customer", "edit_customer", "delete_customer",
    "view_password",
    "create_follow_up", "edit_follow_up", "delete_follow_up",
    "create_media_account", "edit_media_account", "delete_media_account",
    "create_material", "edit_material", "delete_material",
    "complete_service_task",
    "export_data",
    "create_deal", "edit_deal",
    "create_payment", "edit_payment", "delete_payment",
    "create_subscription", "edit_subscription", "delete_subscription",
    "confirm_subscription_renewal", "stop_subscription_renewal", "change_subscription_package",
    "enable_subscription_auto_renew", "switch_subscription_to_manual_collection",
    "create_customer_expense", "edit_customer_expense", "delete_customer_expense",
    "create_company_expense", "edit_company_expense", "delete_company_expense",
    "close_finance_month", "reopen_finance_month",
    "other",
})
# The generic browser endpoint is intentionally not an audit-event factory.
# It can append a clearly labelled user note; trusted business endpoints write
# the audited action types above directly through this service.
CLIENT_OPERATION_ACTION_TYPES = frozenset({"user_note"})
MAX_OPERATION_DETAIL_LENGTH = 2000
MAX_OPERATION_BATCH_SIZE = 50


def build_server_operation_log_data(
    *,
    current_user: Any,
    request: Any,
    action_type: str,
    action_detail: Optional[str] = None,
    customer_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Build immutable audit attribution from the authenticated request.

    Client-provided operator, user, timestamp, and IP values must never enter
    this helper.  Keeping the derivation in one place also lets sensitive
    server-side actions (such as password reveal and customer deletion) write
    the same trusted audit shape before returning success.
    """
    if action_type not in ALLOWED_OPERATION_ACTION_TYPES:
        raise ValueError("Unsupported operation action type")
    if action_detail is not None and len(action_detail) > MAX_OPERATION_DETAIL_LENGTH:
        raise ValueError(f"Operation detail exceeds {MAX_OPERATION_DETAIL_LENGTH} characters")

    operator_name = (
        str(getattr(current_user, "name", "") or "").strip()
        or str(getattr(current_user, "email", "") or "").strip()
        or f"user:{getattr(current_user, 'id', 'unknown')}"
    )
    request_client = getattr(request, "client", None)
    client_host = str(getattr(request_client, "host", "") or "").strip() or None

    return {
        "customer_id": customer_id,
        "action_type": action_type,
        "action_detail": action_detail,
        "operator_name": operator_name[:255],
        "ip_address": client_host[:64] if client_host else None,
        "created_at": datetime.now(timezone.utc),
    }


# ------------------ Service Layer ------------------
class Operation_logsService:
    """Service layer for Operation_logs operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        data: Dict[str, Any],
        user_id: Optional[str] = None,
        *,
        commit: bool = True,
    ) -> Optional[Operation_logs]:
        """Create a new operation_logs"""
        try:
            if user_id:
                data['user_id'] = user_id
            obj = Operation_logs(**data)
            self.db.add(obj)
            if commit:
                await self.db.commit()
                await self.db.refresh(obj)
            else:
                await self.db.flush()
            logger.info(f"Created operation_logs with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating operation_logs: {str(e)}")
            raise

    async def check_ownership(self, obj_id: int, user_id: str) -> bool:
        """Check if user owns this record"""
        try:
            obj = await self.get_by_id(obj_id, user_id=user_id)
            return obj is not None
        except Exception as e:
            logger.error(f"Error checking ownership for operation_logs {obj_id}: {str(e)}")
            return False

    async def get_by_id(self, obj_id: int, user_id: Optional[str] = None) -> Optional[Operation_logs]:
        """Get operation_logs by ID (user can only see their own records)"""
        try:
            query = select(Operation_logs).where(Operation_logs.id == obj_id)
            if user_id:
                query = query.where(Operation_logs.user_id == user_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching operation_logs {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        user_id: Optional[str] = None,
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of operation_logss (user can only see their own records)"""
        try:
            query = select(Operation_logs)
            count_query = select(func.count(Operation_logs.id))
            
            if user_id:
                query = query.where(Operation_logs.user_id == user_id)
                count_query = count_query.where(Operation_logs.user_id == user_id)
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Operation_logs, field):
                        query = query.where(getattr(Operation_logs, field) == value)
                        count_query = count_query.where(getattr(Operation_logs, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Operation_logs, field_name):
                        query = query.order_by(getattr(Operation_logs, field_name).desc())
                else:
                    if hasattr(Operation_logs, sort):
                        query = query.order_by(getattr(Operation_logs, sort))
            else:
                query = query.order_by(Operation_logs.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching operation_logs list: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Operation_logs]:
        """Get operation_logs by any field"""
        try:
            if not hasattr(Operation_logs, field_name):
                raise ValueError(f"Field {field_name} does not exist on Operation_logs")
            result = await self.db.execute(
                select(Operation_logs).where(getattr(Operation_logs, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching operation_logs by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Operation_logs]:
        """Get list of operation_logss filtered by field"""
        try:
            if not hasattr(Operation_logs, field_name):
                raise ValueError(f"Field {field_name} does not exist on Operation_logs")
            result = await self.db.execute(
                select(Operation_logs)
                .where(getattr(Operation_logs, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Operation_logs.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching operation_logss by {field_name}: {str(e)}")
            raise
