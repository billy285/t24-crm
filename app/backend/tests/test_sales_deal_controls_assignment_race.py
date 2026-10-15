"""Real SQLite transaction barriers for prospect assignment/payment races."""
import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.tests.test_sales_dossiers import auth, dossier_api
from models.sales_deal_controls import SalesHandoffChecklists, SalesQuoteRequests
from models.sales_leads import SalesLeads
from services.sales_workflow_locks import lock_sales_workflow


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create_quote", "save_handoff"])
async def test_former_owner_cannot_write_quote_or_handoff_after_transfer(dossier_api, monkeypatch, operation):
    from routers import sales_deal_controls as router
    client, sessions = dossier_api
    staged, release, committed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    stale_read, waiting_lock = asyncio.Event(), asyncio.Event()
    original_scope = router._get_scoped_lead
    seen = []

    async def held_transfer():
        async with sessions() as db:
            await lock_sales_workflow(db, lead_ids=[1], employee_ids=[11, 12])
            row = await db.get(SalesLeads, 1)
            row.assigned_sales_id, row.assigned_sales_name = 12, "Sales B"
            await db.flush()
            staged.set()
            await release.wait()
            await db.commit()
            committed.set()

    async def observed_scope(db, lead_id, user):
        row = await original_scope(db, lead_id, user)
        if router._employee_id(user) == 11:
            seen.append(row.assigned_sales_id)
            stale_read.set()
            await committed.wait()
        return row

    async def observed_lock(db, lead_ids=(), employee_ids=()):
        waiting_lock.set()
        await lock_sales_workflow(db, lead_ids, employee_ids)

    monkeypatch.setattr(router, "_get_scoped_lead", observed_scope)
    monkeypatch.setattr(router, "lock_sales_workflow", observed_lock)
    method, path, payload = ("POST", "/api/v1/sales-deal-controls/1/quotes", {
        "package_name": "Synthetic proposal", "list_amount": 500,
    }) if operation == "create_quote" else ("PUT", "/api/v1/sales-deal-controls/1/handoff", {
        "customer_goal": "Stale former-owner handoff",
    })
    transfer = asyncio.create_task(held_transfer())
    await asyncio.wait_for(staged.wait(), 5)
    request = asyncio.create_task(client.request(method, path, headers=auth(11), json=payload))
    checkpoints = [asyncio.create_task(stale_read.wait()), asyncio.create_task(waiting_lock.wait())]
    try:
        done, _ = await asyncio.wait(checkpoints, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        assert done
        release.set()
        await asyncio.wait_for(transfer, 5)
        response = await asyncio.wait_for(request, 5)
    finally:
        release.set()
        for task in checkpoints:
            task.cancel()
        await asyncio.gather(*checkpoints, return_exceptions=True)
        for task in (transfer, request):
            if not task.done():
                task.cancel()
        await asyncio.gather(transfer, request, return_exceptions=True)
    assert response.status_code == 404, response.text
    assert seen == [], "authority was read before waiting for the assignment transaction"
    async with sessions() as db:
        assert (await db.get(SalesLeads, 1)).assigned_sales_id == 12
        assert await db.scalar(select(func.count()).select_from(SalesQuoteRequests)) == 0
        assert await db.scalar(select(func.count()).select_from(SalesHandoffChecklists)) == 0
    saved = await client.request(method, path, headers=auth(12), json=payload)
    assert saved.status_code == (201 if operation == "create_quote" else 200), saved.text


@pytest.mark.asyncio
async def test_finance_confirmation_rechecks_quote_after_competing_sales_quote_change(dossier_api, monkeypatch):
    from routers import sales_deal_controls as router
    client, sessions = dossier_api
    async with sessions() as db:
        db.add_all([
            SalesQuoteRequests(id=700, lead_id=1, package_name="Old proposal", submitted_by_id=11,
                               list_amount=500, final_amount=500, status="approved"),
            SalesQuoteRequests(id=701, lead_id=1, package_name="Replacement proposal", submitted_by_id=11,
                               list_amount=700, final_amount=700, status="approved"),
            SalesHandoffChecklists(id=800, lead_id=1, quote_id=700, customer_goal="Original brief",
                                   payment_status="pending", finance_payment_confirmed=False, amount_received=0),
        ])
        await db.commit()
    sales_has_lock, release_sales, sales_committed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    finance_read_old_quote, finance_waiting_lock = asyncio.Event(), asyncio.Event()
    original_scope, original_get = router._get_scoped_lead, AsyncSession.get

    async def observed_scope(db, lead_id, user):
        row = await original_scope(db, lead_id, user)
        if router._employee_id(user) == 11:
            sales_has_lock.set()
            await release_sales.wait()
        return row

    async def observed_lock(db, lead_ids=(), employee_ids=()):
        if 1 in employee_ids:
            finance_waiting_lock.set()
        await lock_sales_workflow(db, lead_ids, employee_ids)

    async def observed_get(db, model, ident, *args, **kwargs):
        row = await original_get(db, model, ident, *args, **kwargs)
        if model is SalesQuoteRequests and ident == 700:
            # Only the stale finance request reads the old quote. Sales is
            # changing to 701; fixed finance waits, then also reads 701.
            finance_read_old_quote.set()
            await sales_committed.wait()
        return row

    monkeypatch.setattr(router, "_get_scoped_lead", observed_scope)
    monkeypatch.setattr(router, "lock_sales_workflow", observed_lock)
    monkeypatch.setattr(AsyncSession, "get", observed_get)
    async def sales_change():
        response = await client.put("/api/v1/sales-deal-controls/1/handoff", headers=auth(11),
                                    json={"quote_id": 701, "customer_goal": "Replacement brief"})
        assert response.status_code == 200, response.text
        sales_committed.set()
        return response
    sales = asyncio.create_task(sales_change())
    await asyncio.wait_for(sales_has_lock.wait(), 5)
    finance = asyncio.create_task(client.post("/api/v1/sales-deal-controls/1/handoff/finance-confirmation",
        headers=auth(1), json={"payment_status": "paid", "amount_received": 500,
                              "payment_reference": "Receipt for old 500 proposal"}))
    checkpoints = [asyncio.create_task(finance_read_old_quote.wait()), asyncio.create_task(finance_waiting_lock.wait())]
    try:
        done, _ = await asyncio.wait(checkpoints, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        assert done
        release_sales.set()
        await asyncio.wait_for(sales, 5)
        response = await asyncio.wait_for(finance, 5)
    finally:
        release_sales.set()
        sales_committed.set()
        for task in checkpoints:
            task.cancel()
        await asyncio.gather(*checkpoints, return_exceptions=True)
        for task in (sales, finance):
            if not task.done():
                task.cancel()
        await asyncio.gather(sales, finance, return_exceptions=True)
    assert response.status_code == 400, response.text
    assert not finance_read_old_quote.is_set(), "finance used a quote read before the competing handoff committed"
    async with sessions() as db:
        row = await db.get(SalesHandoffChecklists, 800)
        assert (row.quote_id, row.customer_goal) == (701, "Replacement brief")
        assert not row.finance_payment_confirmed and row.payment_status == "pending"
        assert row.amount_received == 0 and row.payment_reference is None
        assert row.payment_confirmed_by_id is None
    # The same existing formula accepts the correct current-quote amount.
    confirmed = await client.post("/api/v1/sales-deal-controls/1/handoff/finance-confirmation",
        headers=auth(1), json={"payment_status": "paid", "amount_received": 700,
                              "payment_reference": "Receipt for current 700 proposal"})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["quote_id"] == 701 and confirmed.json()["amount_received"] == 700


@pytest.mark.asyncio
async def test_former_team_manager_cannot_review_quote_after_transfer(dossier_api, monkeypatch):
    from routers import sales_deal_controls as router
    client, sessions = dossier_api
    async with sessions() as db:
        db.add(SalesQuoteRequests(id=900, lead_id=1, package_name="Pending team proposal", submitted_by_id=11,
                                 list_amount=500, final_amount=500, status="submitted"))
        await db.commit()
    staged, release, committed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    stale_scope, waiting_lock = asyncio.Event(), asyncio.Event()
    original_scope = router._get_scoped_lead

    async def held_transfer():
        async with sessions() as db:
            await lock_sales_workflow(db, lead_ids=[1], employee_ids=[11, 12])
            lead = await db.get(SalesLeads, 1)
            lead.assigned_sales_id, lead.assigned_sales_name, lead.team_manager_id = 12, "Sales B", None
            await db.flush()
            staged.set()
            await release.wait()
            await db.commit()
            committed.set()

    async def observed_scope(db, lead_id, user):
        row = await original_scope(db, lead_id, user)
        if router._employee_id(user) == 10:
            stale_scope.set()
            await committed.wait()
        return row

    async def observed_lock(db, lead_ids=(), employee_ids=()):
        waiting_lock.set()
        await lock_sales_workflow(db, lead_ids, employee_ids)

    monkeypatch.setattr(router, "_get_scoped_lead", observed_scope)
    monkeypatch.setattr(router, "lock_sales_workflow", observed_lock)
    transfer = asyncio.create_task(held_transfer())
    await asyncio.wait_for(staged.wait(), 5)
    request = asyncio.create_task(client.post("/api/v1/sales-deal-controls/quotes/900/review", headers=auth(10),
                                            json={"decision": "approved", "review_notes": "Stale team approval"}))
    checkpoints = [asyncio.create_task(stale_scope.wait()), asyncio.create_task(waiting_lock.wait())]
    try:
        done, _ = await asyncio.wait(checkpoints, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        assert done
        release.set()
        await asyncio.wait_for(transfer, 5)
        response = await asyncio.wait_for(request, 5)
    finally:
        release.set()
        for task in checkpoints:
            task.cancel()
        await asyncio.gather(*checkpoints, return_exceptions=True)
        for task in (transfer, request):
            if not task.done():
                task.cancel()
        await asyncio.gather(transfer, request, return_exceptions=True)
    assert response.status_code == 404, response.text
    assert not stale_scope.is_set()
    async with sessions() as db:
        quote = await db.get(SalesQuoteRequests, 900)
        assert quote.status == "submitted" and quote.reviewed_by_id is None
        assert quote.final_amount == 500
    authorized = await client.post("/api/v1/sales-deal-controls/quotes/900/review", headers=auth(1),
                                   json={"decision": "approved", "review_notes": "Owner approval"})
    assert authorized.status_code == 200, authorized.text
    assert authorized.json()["status"] == "approved" and authorized.json()["final_amount"] == 500
