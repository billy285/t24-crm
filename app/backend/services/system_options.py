from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.system_options import SystemOption
from schemas.system_options import SystemOptionCreate, SystemOptionUpdate

class SystemOptionService:
    async def get_options_by_category(self, db: AsyncSession, category: str):
        result = await db.execute(select(SystemOption).filter(SystemOption.category == category).order_by(SystemOption.order))
        return result.scalars().all()

    async def get_all_options(self, db: AsyncSession):
        result = await db.execute(select(SystemOption).order_by(SystemOption.category, SystemOption.order))
        return result.scalars().all()

    async def create_option(self, db: AsyncSession, option: SystemOptionCreate):
        db_option = SystemOption(**option.model_dump())
        db.add(db_option)
        await db.commit()
        await db.refresh(db_option)
        return db_option

    async def update_option(self, db: AsyncSession, option_id: int, option: SystemOptionUpdate):
        result = await db.execute(select(SystemOption).filter(SystemOption.id == option_id))
        db_option = result.scalars().first()
        if db_option:
            update_data = option.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_option, key, value)
            await db.commit()
            await db.refresh(db_option)
        return db_option

    async def delete_option(self, db: AsyncSession, option_id: int):
        result = await db.execute(select(SystemOption).filter(SystemOption.id == option_id))
        db_option = result.scalars().first()
        if db_option:
            await db.delete(db_option)
            await db.commit()
        return db_option

system_option_service = SystemOptionService()
