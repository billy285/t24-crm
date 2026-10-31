"""Independent synthetic briefs, scope, calendar and outcome accounting tests."""
import json
from uuid import uuid4
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
import models.media_planning
from models.media_planning import MediaContentPlan as Plan, MediaContentPlanTask as Link
from models.media_operations import MediaOperationTask as Task
from models.customer_access_grants import CustomerAccessGrant
from test_media_operations import media_env, OWNER, OPS, OTHER, ADMIN

PREFIX = "/api/v1/media-planning"


def payload(**updates):
    return {"request_id": str(uuid4()), "customer_id": 10, "title": "Synthetic seasonal plan", "brief": "Only confirmed business details",
        "assignee_id": 2, "variants": [
            {"platform": "google_business", "content": "Google version", "due_at": "2026-11-05T09:00:00-05:00", "timezone": "America/New_York"},
            {"platform": "instagram", "content": "Instagram manual version", "due_at": "2026-11-06T09:00:00-05:00", "timezone": "America/New_York"}], **updates}


async def attach(env):
    from routers.media_planning import router
    env.client._transport.app.include_router(router)


@pytest.mark.asyncio
async def test_plan_atomic_drafts_and_exact_retry_does_not_publish_or_approve(media_env):
    env = media_env
    await attach(env)
    data = payload()
    first = await env.client.post(PREFIX + "/plans", json=data)
    assert first.status_code == 201, first.text
    row = first.json()
    assert [x["platform"] for x in row["items"]] == ["google_business", "instagram"]
    assert all(x["status"] == "draft" and x["revision"] == 1 and x["proof_url"] is None for x in row["items"])
    assert row["items"][0]["publication"] == {"topic_type": "STANDARD"}
    assert row["items"][1]["publication"] is None
    again = await env.client.post(PREFIX + "/plans", json=data)
    assert again.status_code == 201 and again.json() == row
    assert (await env.client.get(PREFIX + "/requests/" + data["request_id"])).json() == row
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Plan)) == 1
        assert await db.scalar(select(func.count()).select_from(Link)) == 2
        assert await db.scalar(select(func.count()).select_from(Task)) == 2


@pytest.mark.asyncio
async def test_same_request_different_variant_is_conflict_and_no_duplicate(media_env):
    env = media_env
    await attach(env)
    data = payload()
    assert (await env.client.post(PREFIX + "/plans", json=data)).status_code == 201
    data["variants"][1]["content"] = "Altered"
    assert (await env.client.post(PREFIX + "/plans", json=data)).status_code == 409
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Task)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("customer_id", 20), ("assignee_id", 6), ("title", ""), ("variants", [])])
async def test_invalid_bundle_leaves_no_partial_task_or_plan(media_env, field, value):
    env = media_env
    await attach(env)
    if field == "customer_id":
        env.user = OPS
    response = await env.client.post(PREFIX + "/plans", json=payload(**{field: value}))
    assert response.status_code in {403, 404, 422}, response.text
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Plan)) == 0
        assert await db.scalar(select(func.count()).select_from(Task)) == 0


@pytest.mark.asyncio
async def test_duplicate_platform_and_invalid_second_time_are_atomic(media_env):
    env = media_env
    await attach(env)
    for duplicate in (True, False):
        data = payload()
        if duplicate:
            data["variants"][1]["platform"] = "google_business"
        else:
            data["variants"][1]["due_at"] = "2026-11-06T09:00:00"
        assert (await env.client.post(PREFIX + "/plans", json=data)).status_code == 422
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Task)) == 0


@pytest.mark.asyncio
async def test_only_assigned_invited_employee_reads_plan_and_calendar(media_env):
    env = media_env
    await attach(env)
    result = (await env.client.post(PREFIX + "/plans", json=payload())).json()
    assert "id" in result, result
    params = {"start": "2026-11-01T00:00:00+08:00", "end": "2026-12-01T00:00:00+08:00"}
    env.user = OTHER
    response = await env.client.get(PREFIX + "/plans")
    assert response.status_code == 200 and response.json()["total"] == 0
    assert (await env.client.get(PREFIX + "/calendar", params=params)).json()["total"] == 0
    env.user = OPS
    assert (await env.client.get(PREFIX + "/plans")).json()["total"] == 1
    calendar = await env.client.get(PREFIX + "/calendar", params=params)
    assert calendar.status_code == 200 and calendar.json()["total"] == 2
    assert "SECRET" not in json.dumps(calendar.json())
    async with env.sessions() as db:
        grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 2, CustomerAccessGrant.customer_id == 10))
        grant.invitation_status = "revoked"
        await db.commit()
    assert (await env.client.get(PREFIX + "/plans")).json()["total"] == 0
    assert (await env.client.get(PREFIX + "/calendar", params=params)).json()["total"] == 0


@pytest.mark.asyncio
async def test_readonly_cannot_create_and_operations_cannot_assign_colleague(media_env):
    env = media_env
    await attach(env)
    env.user = OPS
    assert (await env.client.post(PREFIX + "/plans", json=payload(assignee_id=3))).status_code == 403
    async with env.sessions() as db:
        grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 2, CustomerAccessGrant.customer_id == 10))
        grant.scopes = {"basic": "read_only", "delivery": "read_only", "materials": "read_only"}
        await db.commit()
    assert (await env.client.post(PREFIX + "/plans", json=payload())).status_code in {403, 404}


@pytest.mark.asyncio
async def test_calendar_half_open_range_pagination_and_platform_filter(media_env):
    env = media_env
    await attach(env)
    assert (await env.client.post(PREFIX + "/plans", json=payload())).status_code == 201
    params = {"start": "2026-11-05T14:00:00Z", "end": "2026-11-06T14:00:00Z", "limit": 1}
    response = await env.client.get(PREFIX + "/calendar", params=params)
    assert response.status_code == 200 and response.json()["total"] == 1
    assert response.json()["items"][0]["platform"] == "google_business"
    params["platform"] = "instagram"
    assert (await env.client.get(PREFIX + "/calendar", params=params)).json()["total"] == 0
    params.update(start="2026-01-01T00:00:00Z", end="2026-12-01T00:00:00Z")
    assert (await env.client.get(PREFIX + "/calendar", params=params)).status_code == 422


@pytest.mark.asyncio
async def test_summary_counts_manual_delivery_separately_from_platform_success(media_env):
    env = media_env
    await attach(env)
    result = (await env.client.post(PREFIX + "/plans", json=payload())).json()
    async with env.sessions() as db:
        task = await db.get(Task, result["items"][1]["id"])
        task.status = "completed"
        task.completed_at = datetime(2026, 11, 7, tzinfo=timezone.utc)
        await db.commit()
    params = {"start": "2026-11-01T00:00:00Z", "end": "2026-12-01T00:00:00Z"}
    response = await env.client.get(PREFIX + "/summary", params=params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"]["completed"] == 1 and data["completed_in_period"] == 1
    assert data["provider_totals"] is None or data["provider_totals"]["post_succeeded"] == 0
    env.user = OPS
    assert (await env.client.get(PREFIX + "/summary", params=params)).json()["provider_totals"] is None
