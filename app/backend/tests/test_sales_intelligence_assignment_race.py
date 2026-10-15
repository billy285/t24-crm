"""Profile edits must authorize the actor after competing assignment commits."""
import asyncio
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from backend.tests.test_sales_dossiers import auth, dossier_api
from models.sales_intelligence import SalesInsightEvents, SalesLeadProfiles
from models.sales_leads import SalesLeads
from services.sales_intelligence import TZ
from services.sales_workflow_locks import lock_sales_workflow


@pytest.mark.asyncio
async def test_former_owner_profile_edit_waits_for_transfer_then_rechecks_scope(dossier_api, monkeypatch):
    from routers import sales_intelligence as router

    client, sessions = dossier_api
    staged = asyncio.Event()
    release_transfer = asyncio.Event()
    transfer_committed = asyncio.Event()
    profile_waiting_for_lock = asyncio.Event()
    stale_scope_read = asyncio.Event()
    original_scope = router._get_scoped_lead
    original_lock = lock_sales_workflow
    observed_owners = []

    async def held_transfer():
        async with sessions() as db:
            await original_lock(db, lead_ids=[1], employee_ids=[11, 12])
            lead = await db.get(SalesLeads, 1)
            lead.assigned_sales_id = 12
            lead.assigned_sales_name = "Sales B"
            await db.flush()
            staged.set()
            await release_transfer.wait()
            await db.commit()
            transfer_committed.set()

    async def observed_scope(db, lead_id, user):
        row = await original_scope(db, lead_id, user)
        if router._employee_id(user) == 11:
            observed_owners.append(row.assigned_sales_id)
            stale_scope_read.set()
            # The legacy endpoint reaches here without locking. Preserve that
            # stale identity-map object while the competing transfer commits.
            await transfer_committed.wait()
        return row

    async def observed_lock(db, lead_ids=(), employee_ids=()):
        profile_waiting_for_lock.set()
        await original_lock(db, lead_ids, employee_ids)

    monkeypatch.setattr(router, "_get_scoped_lead", observed_scope)
    monkeypatch.setattr(router, "lock_sales_workflow", observed_lock, raising=False)
    payload = {
        "revision": 1, "pipeline_key": "system", "stage_key": "needs",
        "evidence": "Sales A stale form after handoff", "need_summary": "预约需求",
        "next_step": "旧销售不应覆盖新负责人的下一步",
        "next_step_date": (datetime.now(TZ).date() + timedelta(days=7)).isoformat(),
    }
    async with sessions() as db:
        before = (await db.get(SalesLeadProfiles, 1)).payload_json
        old_deadline = (await db.get(SalesLeads, 1)).next_follow_up_at
        events_before = await db.scalar(select(func.count()).select_from(SalesInsightEvents))

    transfer = asyncio.create_task(held_transfer())
    await asyncio.wait_for(staged.wait(), timeout=5)
    request = asyncio.create_task(client.put("/api/v1/sales-intelligence/leads/1", headers=auth(11), json=payload))
    checkpoints = [asyncio.create_task(stale_scope_read.wait()), asyncio.create_task(profile_waiting_for_lock.wait())]
    try:
        # Whichever checkpoint the endpoint reaches first determines whether it
        # read authority before its workflow lock. No scheduling sleeps needed.
        done, _ = await asyncio.wait(checkpoints, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        assert done, "profile edit reached neither scope nor workflow-lock checkpoint"
        release_transfer.set()
        await asyncio.wait_for(transfer, timeout=5)
        response = await asyncio.wait_for(request, timeout=5)
    finally:
        release_transfer.set()
        for pending in checkpoints:
            pending.cancel()
        await asyncio.gather(*checkpoints, return_exceptions=True)
        if not transfer.done():
            await asyncio.wait_for(transfer, timeout=5)
        if not request.done():
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)

    assert response.status_code == 404, response.text
    assert observed_owners == [], "former-owner authority must not be read before the competing transfer commits"
    async with sessions() as db:
        lead = await db.get(SalesLeads, 1)
        profile = await db.get(SalesLeadProfiles, 1)
        assert (lead.assigned_sales_id, lead.assigned_sales_name) == (12, "Sales B")
        assert lead.next_follow_up_at == old_deadline
        assert profile.revision == 1 and profile.payload_json == before
        assert await db.scalar(select(func.count()).select_from(SalesInsightEvents)) == events_before

    # Serialization does not disable valid profile updates by the new primary.
    saved = await client.put("/api/v1/sales-intelligence/leads/1", headers=auth(12), json=payload)
    assert saved.status_code == 200, saved.text
    async with sessions() as db:
        profile = await db.get(SalesLeadProfiles, 1)
        assert profile.revision == 2
        assert json.loads(profile.payload_json)["next_step"] == payload["next_step"]
        event = (await db.scalars(select(SalesInsightEvents).where(SalesInsightEvents.kind == "profile"))).one()
        assert (event.actor_id, event.owner_id) == (12, 12)
