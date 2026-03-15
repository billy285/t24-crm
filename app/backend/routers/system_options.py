from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from core.database import get_db
from services.system_options import system_option_service
from schemas.system_options import SystemOption, SystemOptionCreate, SystemOptionUpdate

router = APIRouter()

@router.get("/system-options", response_model=List[SystemOption], tags=["System Options"])
async def read_all_options(db: AsyncSession = Depends(get_db)):
    """Retrieve all system options."""
    return await system_option_service.get_all_options(db)

@router.get("/system-options/{category}", response_model=List[SystemOption], tags=["System Options"])
async def read_options_by_category(category: str, db: AsyncSession = Depends(get_db)):
    """Retrieve system options for a specific category."""
    return await system_option_service.get_options_by_category(db, category=category)

@router.post("/system-options", response_model=SystemOption, status_code=201, tags=["System Options"])
async def create_option(option: SystemOptionCreate, db: AsyncSession = Depends(get_db)):
    """Create a new system option."""
    return await system_option_service.create_option(db, option=option)

@router.put("/system-options/{option_id}", response_model=SystemOption, tags=["System Options"])
async def update_option(option_id: int, option: SystemOptionUpdate, db: AsyncSession = Depends(get_db)):
    """Update an existing system option."""
    db_option = await system_option_service.update_option(db, option_id=option_id, option=option)
    if db_option is None:
        raise HTTPException(status_code=404, detail="Option not found")
    return db_option

@router.delete("/system-options/{option_id}", response_model=SystemOption, tags=["System Options"])
async def delete_option(option_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a system option."""
    db_option = await system_option_service.delete_option(db, option_id=option_id)
    if db_option is None:
        raise HTTPException(status_code=404, detail="Option not found")
    return db_option
