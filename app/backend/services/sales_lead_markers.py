from collections.abc import Iterable

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.sales_lead_markers import SalesLeadPriority, SalesLeadStar


def marker_conditions(lead_id, viewer_user_id: str, *, starred=False, priority=False):
    filters = []
    if starred:
        filters.append(exists().where(
            SalesLeadStar.lead_id == lead_id, SalesLeadStar.user_id == viewer_user_id,
        ))
    if priority:
        filters.append(exists().where(SalesLeadPriority.lead_id == lead_id))
    return filters


async def markers_for(db: AsyncSession, lead_ids: Iterable[int], viewer_user_id: str):
    ids = set(lead_ids)
    if not ids:
        return {}
    starred = set((await db.scalars(
        select(SalesLeadStar.lead_id).where(
            SalesLeadStar.user_id == viewer_user_id, SalesLeadStar.lead_id.in_(ids),
        )
    )).all())
    priority = set((await db.scalars(
        select(SalesLeadPriority.lead_id).where(SalesLeadPriority.lead_id.in_(ids))
    )).all())
    return {lead_id: {"starred": lead_id in starred, "priority": lead_id in priority} for lead_id in ids}


async def update_markers(
    db: AsyncSession, lead_id: int, actor_id: str, *,
    starred: bool | None = None, priority: bool | None = None,
):
    if starred is not None:
        star = await db.get(SalesLeadStar, (actor_id, lead_id))
        if starred and star is None:
            db.add(SalesLeadStar(user_id=actor_id, lead_id=lead_id))
        elif not starred and star is not None:
            await db.delete(star)
    if priority is not None:
        mark = await db.get(SalesLeadPriority, lead_id)
        if priority and mark is None:
            db.add(SalesLeadPriority(lead_id=lead_id, marked_by=actor_id))
        elif not priority and mark is not None:
            await db.delete(mark)
    await db.flush()
    return (await markers_for(db, [lead_id], actor_id))[lead_id]
