import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.customer_contacts import Customer_contacts

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class Customer_contactsService:
    """Service layer for Customer_contacts operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> Optional[Customer_contacts]:
        """Create a new customer_contacts"""
        try:
            obj = Customer_contacts(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created customer_contacts with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating customer_contacts: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int) -> Optional[Customer_contacts]:
        """Get customer_contacts by ID"""
        try:
            query = select(Customer_contacts).where(Customer_contacts.id == obj_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching customer_contacts {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of customer_contactss"""
        try:
            query = select(Customer_contacts)
            count_query = select(func.count(Customer_contacts.id))
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Customer_contacts, field):
                        query = query.where(getattr(Customer_contacts, field) == value)
                        count_query = count_query.where(getattr(Customer_contacts, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Customer_contacts, field_name):
                        query = query.order_by(getattr(Customer_contacts, field_name).desc())
                else:
                    if hasattr(Customer_contacts, sort):
                        query = query.order_by(getattr(Customer_contacts, sort))
            else:
                query = query.order_by(Customer_contacts.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching customer_contacts list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Customer_contacts]:
        """Update customer_contacts"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Customer_contacts {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated customer_contacts {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating customer_contacts {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int) -> bool:
        """Delete customer_contacts"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Customer_contacts {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted customer_contacts {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting customer_contacts {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Customer_contacts]:
        """Get customer_contacts by any field"""
        try:
            if not hasattr(Customer_contacts, field_name):
                raise ValueError(f"Field {field_name} does not exist on Customer_contacts")
            result = await self.db.execute(
                select(Customer_contacts).where(getattr(Customer_contacts, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching customer_contacts by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Customer_contacts]:
        """Get list of customer_contactss filtered by field"""
        try:
            if not hasattr(Customer_contacts, field_name):
                raise ValueError(f"Field {field_name} does not exist on Customer_contacts")
            result = await self.db.execute(
                select(Customer_contacts)
                .where(getattr(Customer_contacts, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Customer_contacts.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching customer_contactss by {field_name}: {str(e)}")
            raise