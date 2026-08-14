from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from models.company_roadmap import StrategyRecommendationDecision
from models.tasks import Tasks
from services.tasks import TasksService


@pytest.mark.asyncio
async def test_roadmap_task_status_sync_reopens_and_prevents_delete():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            completed_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
            task = Tasks(
                title="里程碑任务", source_type="company_roadmap", status="completed",
                completion_result="已完成第一轮", completed_at=completed_at,
            )
            db.add(task)
            await db.flush()
            decision = StrategyRecommendationDecision(
                recommendation_key="cash_safety", title="补足安全线",
                status="completed", task_id=task.id,
            )
            db.add(decision)
            await db.commit()
            task_id = task.id

            service = TasksService(db)
            cancelled = await service.update(task_id, {"status": "cancelled"})
            assert cancelled.status == "cancelled"
            assert cancelled.completed_at is None
            await db.refresh(decision)
            assert decision.status == "deferred"

            reopened = await service.update(task_id, {"status": "pending"})
            assert reopened.status == "pending"
            assert reopened.completed_at is None
            await db.refresh(decision)
            assert decision.status == "accepted"

            with pytest.raises(HTTPException) as delete_error:
                await service.delete(task_id)
            assert delete_error.value.status_code == 409
            assert await db.get(Tasks, task_id) is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_roadmap_task_completion_requires_result():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            task = Tasks(title="待处理里程碑", source_type="company_roadmap", status="pending")
            db.add(task)
            await db.flush()
            db.add(StrategyRecommendationDecision(
                recommendation_key="capacity", title="产能复核", status="accepted", task_id=task.id,
            ))
            await db.commit()
            task_id = task.id

            with pytest.raises(ValueError, match="必须填写处理结果"):
                await TasksService(db).update(task_id, {"status": "completed"})
            persisted = await db.get(Tasks, task_id)
            assert persisted.status == "pending"
            assert persisted.completed_at is None
    finally:
        await engine.dispose()
