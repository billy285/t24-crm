"""Scope-checked first-call verification; never starts a call or changes consent."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from schemas.prospect_verification import EntityKind, ProspectVerificationUpdate
from services.prospect_verification import save_verification, verification_view

router = APIRouter(prefix='/api/v1/prospect-verification', tags=['prospect-verification'])


@router.get('/{entity_kind}/{entity_id}')
async def get_verification(entity_kind: EntityKind, entity_id: int,
                           user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await verification_view(db, entity_kind, entity_id, user)


@router.patch('/{entity_kind}/{entity_id}')
async def update_verification(entity_kind: EntityKind, entity_id: int, payload: ProspectVerificationUpdate,
                              user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await save_verification(db, entity_kind, entity_id, user, payload)
        result = await verification_view(db, entity_kind, entity_id, user)
        await db.commit()
        return result
    except Exception:
        await db.rollback()
        raise
