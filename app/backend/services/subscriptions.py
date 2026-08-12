import json
import logging
from datetime import date, datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.subscriptions import Subscriptions
from models.customers import Customers
from services.customers import CustomersService

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class SubscriptionsService:
    """Service layer for Subscriptions operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> Optional[Subscriptions]:
        """Create a new subscriptions"""
        try:
            obj = Subscriptions(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created subscriptions with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating subscriptions: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int, scope_user: Optional[Any] = None) -> Optional[Subscriptions]:
        """Get subscriptions by ID"""
        try:
            query = select(Subscriptions).where(Subscriptions.id == obj_id)
            scope_filter = CustomersService(self.db)._scope_filter(scope_user)
            if scope_filter is not None:
                query = query.join(Customers, Customers.id == Subscriptions.customer_id).where(scope_filter)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching subscriptions {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
        scope_user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of subscriptionss"""
        try:
            query = select(Subscriptions)
            count_query = select(func.count(Subscriptions.id))
            scope_filter = CustomersService(self.db)._scope_filter(scope_user)
            if scope_filter is not None:
                query = query.join(Customers, Customers.id == Subscriptions.customer_id).where(scope_filter)
                count_query = count_query.join(Customers, Customers.id == Subscriptions.customer_id).where(scope_filter)
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Subscriptions, field):
                        query = query.where(getattr(Subscriptions, field) == value)
                        count_query = count_query.where(getattr(Subscriptions, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Subscriptions, field_name):
                        query = query.order_by(getattr(Subscriptions, field_name).desc())
                else:
                    if hasattr(Subscriptions, sort):
                        query = query.order_by(getattr(Subscriptions, sort))
            else:
                query = query.order_by(Subscriptions.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching subscriptions list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Subscriptions]:
        """Update subscriptions"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Subscriptions {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated subscriptions {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating subscriptions {obj_id}: {str(e)}")
            raise

    async def mark_package_changed(
        self,
        obj_id: int,
        replacement_ids: List[int],
        effective_date: date,
        reason: Optional[str] = None,
    ) -> tuple[Subscriptions, List[Subscriptions]]:
        """Archive an old package and link it to existing replacement packages atomically."""
        try:
            old_result = await self.db.execute(
                select(Subscriptions).where(Subscriptions.id == obj_id).with_for_update()
            )
            old_subscription = old_result.scalar_one_or_none()
            if not old_subscription:
                raise ValueError("原套餐不存在")
            if old_subscription.status in {"stopped", "lost", "paused", "upgraded"}:
                raise ValueError("原套餐已经归档，不能重复执行套餐变更")

            unique_replacement_ids = sorted({int(item_id) for item_id in replacement_ids if int(item_id) != obj_id})
            if not unique_replacement_ids:
                raise ValueError("请至少选择一个替代套餐")

            replacement_result = await self.db.execute(
                select(Subscriptions)
                .where(Subscriptions.id.in_(unique_replacement_ids))
                .with_for_update()
            )
            replacements = list(replacement_result.scalars().all())
            if len(replacements) != len(unique_replacement_ids):
                raise ValueError("部分替代套餐不存在，请刷新后重试")
            if any(item.customer_id != old_subscription.customer_id for item in replacements):
                raise ValueError("替代套餐必须属于同一客户")
            if old_subscription.business_line_id and any(
                item.business_line_id and item.business_line_id != old_subscription.business_line_id
                for item in replacements
            ):
                raise ValueError("套餐变更只能在同一业务线内替换；跨业务线请新增独立项目")
            if any(item.status in {"stopped", "lost", "paused", "upgraded"} for item in replacements):
                raise ValueError("已归档套餐不能作为新的替代套餐")

            now = datetime.now(timezone.utc)
            change_payload = {
                "type": "package_changed",
                "effective_date": effective_date.isoformat(),
                "replacement_ids": unique_replacement_ids,
                "replacement_names": [item.package_name for item in replacements],
                "reason": (reason or "").strip() or None,
            }
            old_subscription.auto_renew = False
            old_subscription.next_payment_date = None
            old_subscription.status = "upgraded"
            old_subscription.renewal_result = json.dumps(change_payload, ensure_ascii=False, separators=(",", ":"))
            old_subscription.updated_at = now

            await self.db.commit()
            await self.db.refresh(old_subscription)
            for replacement in replacements:
                await self.db.refresh(replacement)
            logger.info(
                "Archived subscription %s as package-changed; replacements=%s",
                obj_id,
                unique_replacement_ids,
            )
            return old_subscription, replacements
        except Exception as e:
            await self.db.rollback()
            logger.error("Error changing package for subscription %s: %s", obj_id, str(e))
            raise

    async def delete(self, obj_id: int) -> bool:
        """Delete subscriptions"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Subscriptions {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted subscriptions {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting subscriptions {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Subscriptions]:
        """Get subscriptions by any field"""
        try:
            if not hasattr(Subscriptions, field_name):
                raise ValueError(f"Field {field_name} does not exist on Subscriptions")
            result = await self.db.execute(
                select(Subscriptions).where(getattr(Subscriptions, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching subscriptions by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Subscriptions]:
        """Get list of subscriptionss filtered by field"""
        try:
            if not hasattr(Subscriptions, field_name):
                raise ValueError(f"Field {field_name} does not exist on Subscriptions")
            result = await self.db.execute(
                select(Subscriptions)
                .where(getattr(Subscriptions, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Subscriptions.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching subscriptionss by {field_name}: {str(e)}")
            raise
