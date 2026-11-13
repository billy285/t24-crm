"""Independent company-statement acceptance; synthetic CSV/provider/file SQLite only."""
import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.tests.test_sales_catalog_handoffs import headers, sale_api
from core.database import Base
from models.customers import Customers
from models.employees import Employees
from models.payments import Payments
from models.stripe_history_reconciliation import StripeHistoryAudit as Audit, StripeHistoryBinding as Binding, StripeHistoryInvoiceReview as Review, StripeHistoryPosting as Posting, StripeHistoryPreview as Preview
from models.subscriptions import Subscriptions
from services import stripe_bank_reconciliation as bank, stripe_history_provider as provider
from services.emp_auth import create_access_token
from services.sales_payment_catalog import STRIPE_ACCOUNT_ID

API = "/api/v1/stripe-history-reconciliation/bank"
CLOCK = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
CSV = "Date,Amount,Description,Reference\n2026-11-12,208.83,SYNTHETIC STRIPE DEPOSIT,BANK-SYNTHETIC-001\n2026-11-12,-4.00,SYNTHETIC COST,COST-SYNTHETIC\n"
KEY = "rk_live_SYNTHETIC_BANK_TEST_NEVER_REAL_1234567890"


def second_owner():
    return {"Authorization": "Bearer " + create_access_token({"emp_id": 2, "email": "second-owner@example.com", "role": "super_admin", "name": "Synthetic second owner"})}


def payout(identity="po_synthetic", **changes):
    return {"id": identity, "object": "payout", "livemode": True, "amount": 20883, "currency": "usd",
        "arrival_date": int(datetime(2026, 11, 12, tzinfo=timezone.utc).timestamp()), "status": "paid",
        "automatic": True, "type": "bank_account", "destination": "ba_SYNTHETIC_ONLY", **changes}


def transaction(identity="txn_synthetic", net=20883, **changes):
    return {"id": identity, "object": "balance_transaction", "currency": "usd", "status": "available",
        "net": net, "type": "charge", "source": "ch_SYNTHETIC_ONLY", **changes}


class FakeBankReader:
    def __init__(self):
        self.payout_rows = {key: payout(key) for key in ("po_synthetic", "po_second")}
        self.pages = {key: {None: ([transaction()], False)} for key in self.payout_rows}
        self.calls = []
        self.on_payout = None

    async def payouts(self, starting_after=None):
        self.calls.append(("payouts", starting_after))
        return copy.deepcopy(list(self.payout_rows.values())), False

    async def payout(self, identity):
        self.calls.append(("payout", identity))
        if self.on_payout:
            self.on_payout(identity)
        await asyncio.sleep(0)
        return copy.deepcopy(self.payout_rows[identity])

    async def payout_transactions(self, identity, starting_after=None):
        self.calls.append(("transactions", identity, starting_after))
        return copy.deepcopy(self.pages[identity][starting_after])


@pytest_asyncio.fixture
async def bank_api(sale_api, monkeypatch):
    client, sessions = sale_api
    fake = FakeBankReader()
    monkeypatch.setattr(provider, "reader", lambda: fake)
    monkeypatch.setattr(bank, "now", lambda: CLOCK)
    async with sessions() as db:
        db.add(Employees(id=2, user_id="u2", name="Synthetic second owner", role="super_admin", status="active"))
        # A pre-existing financial row must never be rewritten by bank matching.
        db.add(Payments(id=901, customer_id=901, amount_due=198, amount_paid=198, management_amount=198,
            stripe_fee_amount=6.5, net_amount=208.83, currency="USD", user_id="synthetic-owner"))
        await db.commit()
    return client, sessions, fake


async def state(sessions):
    async with sessions() as db:
        return {table.name: sorted(json.dumps(dict(row._mapping), sort_keys=True, default=str)
            for row in (await db.execute(select(table))).all()) for table in Base.metadata.sorted_tables
            if table.name not in {"stripe_history_previews", "stripe_history_audits"}}


async def statement(client, *, csv_text=CSV, auth=None, **changes):
    value = {"csv_text": csv_text, "account_label": "Synthetic company USD account", "currency": "USD",
        "date_format": "ymd", "date_column": "Date", "amount_column": "Amount", "description_column": "Description",
        "reference_column": "Reference", **changes}
    response = await client.post(API + "/statements/preview", headers=auth or headers(1), json=value)
    assert response.status_code == 200, response.text
    return response.json()


async def match_preview(client, statement_token, *, identity="po_synthetic", auth=None, row=2):
    response = await client.post(API + "/matches/preview", headers=auth or headers(1),
        json={"statement_token": statement_token, "row_index": row, "payout_id": identity})
    assert response.status_code == 200, response.text
    return response.json()


async def confirm(client, token, *, auth=None, **changes):
    return await client.post(API + "/matches/confirm", headers=auth or headers(1),
        json={"token": token, "owner_verified": True, "note": "Synthetic owner verified bank statement", **changes})


@pytest.mark.asyncio
async def test_inspect_preview_confirm_replay_void_only_write_audits(bank_api):
    client, sessions, fake = bank_api
    before = await state(sessions)
    inspected = await client.post(API + "/statements/inspect", headers=headers(1), json={"csv_text": CSV})
    assert inspected.status_code == 200 and inspected.json()["headers"] == ["Date", "Amount", "Description", "Reference"]
    assert inspected.json()["row_count"] == 2 and inspected.json()["writes_ledger"] is False
    assert "no-store" in inspected.headers["cache-control"] and fake.calls == []
    uploaded = await statement(client)
    assert len(uploaded["rows"]) == 1 and uploaded["rows"][0]["amount_minor"] == 20883
    listing = await client.get(API + "/payouts", headers=headers(1))
    assert listing.status_code == 200 and listing.json()["bank_deposit_proven"] is False
    preview = await match_preview(client, uploaded["token"])
    assert preview["transaction_count"] == 1 and preview["requires_owner_confirmation"] is True
    assert await state(sessions) == before
    confirmed = await confirm(client, preview["token"])
    assert confirmed.status_code == 200, confirmed.text
    data = confirmed.json()
    assert not data["idempotent_replay"] and not data["ledger_writes"]
    assert data["item"]["status"] == "statement_manually_matched" and data["item"]["amount_minor"] == 20883
    replay = await confirm(client, preview["token"])
    assert replay.status_code == 200 and replay.json()["idempotent_replay"]
    overview = (await client.get(API + "/overview", headers=headers(1))).json()
    assert overview["total"] == 1 and not overview["ledger_writes"] and not overview["provider_writes"]
    match_id = data["item"]["id"]
    void = await client.post(f"{API}/matches/{match_id}/void", headers=headers(1), json={"owner_verified": True, "note": "Synthetic correction"})
    assert void.status_code == 200 and not void.json()["idempotent_replay"]
    assert (await confirm(client, preview["token"])).status_code == 409
    replay_void = await client.post(f"{API}/matches/{match_id}/void", headers=headers(1), json={"owner_verified": True, "note": "Synthetic correction"})
    assert replay_void.status_code == 200 and replay_void.json()["idempotent_replay"]
    assert (await client.get(API + "/overview", headers=headers(1))).json()["total"] == 0
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "bank_match_confirmed")) == 1
        assert await db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "bank_match_voided")) == 1
    assert await state(sessions) == before


@pytest.mark.asyncio
async def test_staff_unauthenticated_and_revoked_owner_never_read_or_create_bank_proofs(bank_api):
    client, sessions, fake = bank_api
    for auth in ({}, *[headers(actor) for actor in (11, 12, 13, 14, 15, 16, 17)]):
        for method, endpoint, body in [("GET", "/overview", None), ("GET", "/payouts", None),
            ("POST", "/statements/inspect", {"csv_text": CSV}), ("POST", "/matches/confirm", {"token": "a" * 43, "owner_verified": True, "note": "Synthetic confirm"}),
            ("POST", "/matches/1/void", {"owner_verified": True, "note": "Synthetic void"})]:
            response = await client.request(method, API + endpoint, headers=auth, json=body)
            assert response.status_code in {401, 403}, response.text
    assert fake.calls == []
    async with sessions() as db:
        owner = await db.get(Employees, 1)
        owner.status = "inactive"
        await db.commit()
    assert (await client.get(API + "/overview", headers=headers(1))).status_code == 403


@pytest.mark.asyncio
async def test_preview_tokens_are_actor_and_purpose_bound_including_confirmed_replay(bank_api):
    client, sessions, fake = bank_api
    uploaded = await statement(client)
    response = await client.post(API + "/matches/preview", headers=second_owner(),
        json={"statement_token": uploaded["token"], "row_index": 2, "payout_id": "po_synthetic"})
    assert response.status_code == 409 and fake.calls == []
    assert (await confirm(client, uploaded["token"])).status_code == 409
    preview = await match_preview(client, uploaded["token"])
    assert (await confirm(client, preview["token"], auth=second_owner())).status_code == 409
    # Bank tokens cannot be used as the old subscription-binding capability.
    calls = list(fake.calls)
    for token in (uploaded["token"], preview["token"]):
        response = await client.post("/api/v1/stripe-history-reconciliation/bindings", headers=headers(1),
            json={"token": token, "owner_verified": True, "accepted_warning_codes": []})
        assert response.status_code == 409, response.text
    assert fake.calls == calls
    assert (await confirm(client, preview["token"])).status_code == 200
    # A successful old match is not a capability for a different owner to replay.
    assert (await confirm(client, preview["token"], auth=second_owner())).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"currency": "EUR"}, {"amount_column": "Date"}, {"date_column": "Missing"}, {"date_format": "unknown"},
    {"csv_text": "Date,Amount,Date\n2026-11-12,208.83,x\n"},
    {"csv_text": "Date,Amount,Description,Reference\n2026-11-12,208.831,test,R\n"},
    {"csv_text": "Date,Amount,Description,Reference\n2026-11-12,NaN,test,R\n"},
    {"csv_text": 'Date,Amount,Description,Reference\n2026-11-12,"208,83",test,R\n'},
    {"csv_text": 'Date,Amount,Description,Reference\n2026-11-12,"20,8.83",test,R\n'},
    {"csv_text": "Date,Amount,Description,Reference\n2099-11-12,208.83,test,R\n"},
    {"csv_text": "Date,Amount,Description,Reference\n11/12/2026,208.83,test,R\n"},
])
async def test_statement_columns_currency_dates_and_money_fail_closed(bank_api, change):
    client, sessions, fake = bank_api
    value = {"csv_text": CSV, "account_label": "Synthetic company USD account", "currency": "USD", "date_format": "ymd",
        "date_column": "Date", "amount_column": "Amount", "description_column": "Description", "reference_column": "Reference", **change}
    response = await client.post(API + "/statements/preview", headers=headers(1), json=value)
    assert response.status_code == 422, response.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Preview)) == 0
    assert fake.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"status": "failed"}, {"status": "pending"}, {"automatic": False},
    {"type": "card"}, {"currency": "eur"}, {"livemode": False}, {"amount": 20884},
    {"arrival_date": int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())}])
async def test_failed_manual_foreign_or_mismatching_payout_never_matches(bank_api, changes):
    client, sessions, fake = bank_api
    uploaded = await statement(client)
    fake.payout_rows["po_synthetic"].update(changes)
    if "amount" in changes:
        fake.pages["po_synthetic"][None] = ([transaction(net=changes["amount"])], False)
    response = await client.post(API + "/matches/preview", headers=headers(1),
        json={"statement_token": uploaded["token"], "row_index": 2, "payout_id": "po_synthetic"})
    assert response.status_code == 409, response.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Audit)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing_page", "duplicate", "net_mismatch", "currency", "unavailable", "payout_row", "fractional_net", "too_many_pages"])
async def test_full_transaction_pages_unique_ids_and_net_total_are_required(bank_api, monkeypatch, case):
    client, sessions, fake = bank_api
    uploaded = await statement(client)
    if case == "missing_page": fake.pages["po_synthetic"] = {None: ([], True)}
    if case == "duplicate": fake.pages["po_synthetic"] = {None: ([transaction()], True), "txn_synthetic": ([transaction()], False)}
    if case == "net_mismatch": fake.pages["po_synthetic"][None] = ([transaction(net=20882)], False)
    if case == "currency": fake.pages["po_synthetic"][None] = ([transaction(currency="eur")], False)
    if case == "unavailable": fake.pages["po_synthetic"][None] = ([transaction(status="pending")], False)
    if case == "payout_row": fake.pages["po_synthetic"][None] = ([transaction(type="payout")], False)
    if case == "fractional_net": fake.pages["po_synthetic"][None] = ([transaction(net=20883.0)], False)
    if case == "too_many_pages":
        monkeypatch.setattr(bank, "MAX_PAYOUT_PAGES", 2)
        fake.pages["po_synthetic"] = {None: ([transaction("txn_first", 100)], True), "txn_first": ([transaction("txn_second", 100)], True)}
    response = await client.post(API + "/matches/preview", headers=headers(1),
        json={"statement_token": uploaded["token"], "row_index": 2, "payout_id": "po_synthetic"})
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_multipage_net_with_negative_adjustment_and_fresh_confirm_change(bank_api):
    client, sessions, fake = bank_api
    fake.pages["po_synthetic"] = {None: ([transaction("txn_positive", 21000)], True),
        "txn_positive": ([transaction("txn_adjustment", -117, type="adjustment")], False)}
    uploaded = await statement(client)
    preview = await match_preview(client, uploaded["token"])
    assert preview["transaction_count"] == 2
    assert ("transactions", "po_synthetic", "txn_positive") in fake.calls
    fake.payout_rows["po_synthetic"]["status"] = "failed"
    assert (await confirm(client, preview["token"])).status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Audit)) == 0


@pytest.mark.asyncio
async def test_token_expiry_owner_confirmation_and_changed_payout_during_read(bank_api):
    client, sessions, fake = bank_api
    uploaded = await statement(client)
    preview = await match_preview(client, uploaded["token"])
    assert (await confirm(client, preview["token"], owner_verified=False)).status_code == 422
    async with sessions() as db:
        record = await db.get(Preview, preview["token"])
        record.expires_at = CLOCK - timedelta(seconds=1)
        await db.commit()
    assert (await confirm(client, preview["token"])).status_code == 409
    reads = [0]
    def mutate(identity):
        reads[0] += 1
        if reads[0] == 2:
            fake.payout_rows[identity]["amount"] += 1
    fake.on_payout = mutate
    response = await client.post(API + "/matches/preview", headers=headers(1),
        json={"statement_token": uploaded["token"], "row_index": 2, "payout_id": "po_synthetic"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_same_payout_total_with_changed_transaction_identity_requires_new_preview(bank_api):
    client, sessions, fake = bank_api
    uploaded = await statement(client)
    preview = await match_preview(client, uploaded["token"])
    fake.pages["po_synthetic"][None] = ([transaction("txn_changed_identity")], False)
    response = await confirm(client, preview["token"])
    assert response.status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Audit)) == 0


@pytest.mark.asyncio
async def test_owner_revoked_during_provider_read_is_rechecked_before_audit_commit(bank_api, monkeypatch):
    client, sessions, fake = bank_api
    uploaded = await statement(client)
    preview = await match_preview(client, uploaded["token"])
    original = bank.payout_evidence
    async def revoke_after_read(identity):
        result = await original(identity)
        async with sessions() as db:
            owner = await db.get(Employees, 1)
            owner.role = "sales"
            await db.commit()
        return result
    monkeypatch.setattr(bank, "payout_evidence", revoke_after_read)
    response = await confirm(client, preview["token"])
    assert response.status_code == 403
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Audit)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["preview", "confirm"])
async def test_provider_timeout_returns_retryable_private_error_without_matching_or_ledger_write(bank_api, monkeypatch, phase):
    client, sessions, fake = bank_api
    uploaded = await statement(client)
    preview = await match_preview(client, uploaded["token"])
    before = await state(sessions)
    async def timed_out(_identity):
        raise asyncio.TimeoutError("SYNTHETIC_INTERNAL_TIMEOUT")
    monkeypatch.setattr(bank, "payout_evidence", timed_out)
    if phase == "preview":
        response = await client.post(API + "/matches/preview", headers=headers(1),
            json={"statement_token": uploaded["token"], "row_index": 2, "payout_id": "po_synthetic"})
    else:
        response = await confirm(client, preview["token"])
    assert response.status_code == 503, response.text
    assert "SYNTHETIC_INTERNAL_TIMEOUT" not in response.text and "no-store" in response.headers["cache-control"]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Audit)) == 0
    assert await state(sessions) == before


@pytest.mark.asyncio
async def test_duplicate_csv_row_same_bank_fingerprint_and_payout_are_not_double_matched(bank_api):
    client, sessions, fake = bank_api
    duplicate_csv = CSV + "2026-11-12,208.83,SYNTHETIC STRIPE DEPOSIT,BANK-SYNTHETIC-001\n"
    uploaded = await statement(client, csv_text=duplicate_csv)
    response = await client.post(API + "/matches/preview", headers=headers(1),
        json={"statement_token": uploaded["token"], "row_index": 2, "payout_id": "po_synthetic"})
    assert response.status_code == 409 and fake.calls == []
    first = await statement(client)
    preview = await match_preview(client, first["token"])
    assert (await confirm(client, preview["token"])).status_code == 200
    # Different provider payout cannot consume the same bank transaction again.
    second = await statement(client, csv_text=CSV + "2026-11-11,-1,Other Cost,OTHER\n")
    duplicate_row = await match_preview(client, second["token"], identity="po_second")
    assert (await confirm(client, duplicate_row["token"])).status_code == 409
    # Different bank transaction cannot consume the same payout again.
    other = await statement(client, csv_text=CSV.replace("BANK-SYNTHETIC-001", "BANK-SYNTHETIC-002"))
    duplicate_payout = await match_preview(client, other["token"])
    assert (await confirm(client, duplicate_payout["token"])).status_code == 409


@pytest.mark.asyncio
async def test_two_file_sqlite_connections_cannot_confirm_same_payout_twice(bank_api, monkeypatch):
    client, sessions, fake = bank_api
    first = await statement(client)
    second = await statement(client, csv_text=CSV.replace("BANK-SYNTHETIC-001", "BANK-SYNTHETIC-002"))
    previews = [await match_preview(client, item["token"]) for item in (first, second)]
    engine = sessions.kw["bind"]
    assert engine.url.database and engine.url.database.endswith("sale.db") and engine.url.database != ":memory:"
    original_owner = bank.owner
    gate, arrivals, connections = asyncio.Event(), [0], set()
    async def concurrent_owner(db, user):
        await original_owner(db, user)
        if arrivals[0] < 2:
            connection = await db.connection()
            connections.add(id(connection.sync_connection.connection.dbapi_connection))
            arrivals[0] += 1
            if arrivals[0] == 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), timeout=5)
    monkeypatch.setattr(bank, "owner", concurrent_owner)
    before = await state(sessions)
    responses = await asyncio.gather(*(confirm(client, item["token"]) for item in previews))
    assert sorted(response.status_code for response in responses) == [200, 409], [response.text for response in responses]
    assert len(connections) == 2  # actual separate file-backed SQLite connections
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "bank_match_confirmed")) == 1
    assert await state(sessions) == before


@pytest.mark.asyncio
async def test_provider_bank_reader_uses_only_fixed_account_get_and_payout_filter():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "api.stripe.com"
        assert request.headers["stripe-account"] == STRIPE_ACCOUNT_ID
        if request.url.path == "/v1/balance": return httpx.Response(200, json={"object": "balance", "livemode": True})
        if request.url.path == "/v1/payouts/po_synthetic": return httpx.Response(200, json=payout())
        if request.url.path == "/v1/payouts": return httpx.Response(200, json={"object": "list", "data": [payout()], "has_more": False})
        assert request.url.path == "/v1/balance_transactions"
        assert request.url.params["payout"] == "po_synthetic" and request.url.params["limit"] == "10"
        assert request.url.params["starting_after"] == "txn_previous"
        return httpx.Response(200, json={"object": "list", "data": [transaction()], "has_more": False})
    reader = provider.StripeHistoryReader(secret=KEY, transport=httpx.MockTransport(handler))
    assert len((await reader.payouts())[0]) == 1
    assert (await reader.payout("po_synthetic"))["id"] == "po_synthetic"
    assert len((await reader.payout_transactions("po_synthetic", "txn_previous"))[0]) == 1
    count = len(calls)
    for path in ("/v1/refunds", "/v1/payouts/po_synthetic/cancel", "/v1/balance_transactions/txn_synthetic", "/v1/../private"):
        with pytest.raises(HTTPException):
            await reader._get(path)
    assert len(calls) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [
    {"object": "list", "data": [transaction()] * 11, "has_more": False},
    {"object": "list", "data": [transaction()], "has_more": "false"},
    {"object": "list", "data": [{"object": "charge"}], "has_more": False},
])
async def test_provider_rejects_unbounded_or_malformed_payout_transaction_pages(page):
    def handler(request):
        if request.url.path == "/v1/balance": return httpx.Response(200, json={"object": "balance", "livemode": True})
        return httpx.Response(200, json=page)
    reader = provider.StripeHistoryReader(secret=KEY, transport=httpx.MockTransport(handler))
    with pytest.raises(HTTPException) as caught:
        await reader.payout_transactions("po_synthetic")
    assert caught.value.status_code == 503


@pytest.mark.parametrize("value,expected", [("$1,208.83", 120883), ("208.8", 20880), ("(4.00)", -400)])
def test_standard_usd_amounts_are_supported_without_guessing_decimal_comma(value, expected):
    assert bank.amount_minor(value) == expected


def test_blank_csv_line_flood_is_bounded_by_row_limit_before_building_all_rows():
    with pytest.raises(HTTPException) as caught:
        bank.csv_rows("Date,Amount\n" + "\n" * 100000)
    assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_explicit_mdy_date_column_preserves_same_bank_day(bank_api):
    client, sessions, fake = bank_api
    uploaded = await statement(client, csv_text=CSV.replace("2026-11-12", "11/12/2026"), date_format="mdy")
    assert uploaded["rows"][0]["date"] == "2026-11-12"


async def seed_posted_invoice(sessions):
    snapshot = {"balance_transaction_id": "txn_synthetic", "stripe_charge_id": "ch_SYNTHETIC_ONLY",
        "net_minor": 20883, "issues": []}
    fingerprint = bank.digest(snapshot)
    async with sessions() as db:
        db.add(Customers(id=901, business_name="Synthetic linked service", contact_name="Synthetic owner", phone="+12125550901"))
        await db.flush()
        db.add(Subscriptions(id=901, customer_id=901, package_name="Synthetic service", package_price=198, status="active", billing_cycle="monthly"))
        await db.flush()
        db.add(Binding(id=901, account_id=STRIPE_ACCOUNT_ID, livemode=True, stripe_subscription_id="sub_synthetic_bank",
            stripe_customer_id="cus_synthetic_bank", crm_subscription_id=901, customer_id=901,
            crm_snapshot={}, price_snapshot={}, income_type="management_fee", sync_from="2026-01-01", status="active",
            revision=1, needs_refresh=False, pilot_evidence={}, pilot_validated=False, verified_by_id=1))
        await db.flush()
        db.add(Review(id=901, account_id=STRIPE_ACCOUNT_ID, livemode=True, stripe_invoice_id="in_synthetic_bank", binding_id=901,
            status="confirmed", snapshot=snapshot, fingerprint=fingerprint, revision=1, needs_refresh=False))
        await db.flush()
        db.add(Posting(review_id=901, account_id=STRIPE_ACCOUNT_ID, livemode=True, stripe_charge_id="ch_SYNTHETIC_ONLY",
            payment_id=901, action="create_payment", fingerprint=fingerprint, verified_by_id=1, verification_note="Synthetic confirmed receipt"))
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("transaction_type", ["charge", "payment"])
async def test_bank_match_links_only_original_immutable_posted_charge_proof(bank_api, transaction_type):
    client, sessions, fake = bank_api
    await seed_posted_invoice(sessions)
    fake.pages["po_synthetic"][None][0][0]["type"] = transaction_type
    before = await state(sessions)
    uploaded = await statement(client)
    preview = await match_preview(client, uploaded["token"])
    response = await confirm(client, preview["token"])
    assert response.status_code == 200, response.text
    assert response.json()["item"]["review_ids"] == [901]
    assert response.json()["item"]["payment_ids"] == [901]
    assert await state(sessions) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["fingerprint", "needs_refresh", "issues", "snapshot_charge", "posting_charge", "net", "adjustment", "zero_charge", "foreign_account"])
async def test_changed_or_noncharge_review_never_marks_old_payment_as_bank_matched(bank_api, mutation):
    client, sessions, fake = bank_api
    await seed_posted_invoice(sessions)
    async with sessions() as db:
        review = await db.get(Review, 901)
        if mutation == "fingerprint": review.fingerprint = "0" * 64
        if mutation == "needs_refresh": review.needs_refresh = True
        if mutation == "issues": review.snapshot = {**review.snapshot, "issues": ["refund_or_dispute"]}
        if mutation == "snapshot_charge": review.snapshot = {**review.snapshot, "stripe_charge_id": "ch_other"}
        if mutation == "posting_charge": (await db.get(Posting, 901)).stripe_charge_id = "ch_other"
        if mutation == "net": review.snapshot = {**review.snapshot, "net_minor": 20882}
        if mutation == "foreign_account": review.account_id = "acct_SYNTHETIC_FOREIGN"
        await db.commit()
    if mutation == "adjustment": fake.pages["po_synthetic"][None][0][0]["type"] = "adjustment"
    if mutation == "zero_charge": fake.pages["po_synthetic"][None] = ([transaction(net=0), transaction("txn_adjustment", 20883, type="adjustment")], False)
    before = await state(sessions)
    uploaded = await statement(client)
    preview = await match_preview(client, uploaded["token"])
    response = await confirm(client, preview["token"])
    assert response.status_code == 200, response.text
    assert response.json()["item"]["review_ids"] == response.json()["item"]["payment_ids"] == []
    assert await state(sessions) == before
