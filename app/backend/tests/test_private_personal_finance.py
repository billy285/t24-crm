"""Real owner auth + separate on-disk books; synthetic data only."""
import asyncio
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

import pytest

from test_private_workspace_app import private_app  # noqa: F401
from services import private_workspace as storage


PREFIX = "/api/v1/private-workspace/personal-finance"
PERIOD = "?start_date=2026-10-01&end_date=2026-10-31"


async def request(app, method, path, data=None, expected=200, owner=1):
    if method == "POST" and path == "/bootstrap" and data is None:
        data = {"client_request_id": str(uuid4())}
    result = await app.client.request(method, PREFIX + path, headers=app.headers(owner), json=data)
    assert result.status_code == expected, result.text
    assert result.headers["cache-control"] == "no-store"
    return result.json()


async def create(app, path, data):
    return await request(app, "POST", path, {"client_request_id": str(uuid4()), **data}, expected=201)


async def books(app, amount=100000):
    initial = await request(app, "POST", "/bootstrap", {"client_request_id": str(uuid4())})
    account = await create(app, "/accounts", {"name": "测试银行卡", "kind": "bank", "opening_balance_minor": amount})
    expense = next(x for x in initial["categories"] if x["kind"] == "expense")
    income = next(x for x in initial["categories"] if x["kind"] == "income")
    return account, expense, income


def entry(account, kind="expense", amount=100, category=None, debt=None, **extra):
    result = {"kind": kind, "amount_minor": amount, "account_id": account["id"],
              "entry_date": "2026-10-12", "client_request_id": str(uuid4()), **extra}
    if category:
        result["category_id"] = category["id"]
    if debt:
        result["debt_id"] = debt["id"]
    return result


@pytest.mark.asyncio
async def test_zero_start_persistent_crud_and_crm_untouched(private_app):
    app = private_app
    digest = hashlib.sha256(app.business_path.read_bytes()).hexdigest()
    empty = await request(app, "GET", "/state")
    assert empty == {"initialized": False, "currency": "CNY", "budget_minor": None,
                     "categories": [], "accounts": [], "debts": [], "plans": [], "goals": []}
    first = await request(app, "POST", "/bootstrap")
    again = await request(app, "POST", "/bootstrap")
    assert first == again and first["initialized"]
    assert len(first["accounts"]) == 1 and first["accounts"][0]["balance_minor"] == 0
    assert first["debts"] == first["plans"] == first["goals"] == []
    category = await create(app, "/categories", {"name": "自定义分类", "kind": "expense", "sort_order": 99})
    changed = await request(app, "PATCH", "/categories/" + category["id"], {"name": "家庭", "sort_order": 2})
    assert changed["name"] == "家庭" and changed["sort_order"] == 2
    account = await create(app, "/accounts", {"name": "微信", "kind": "wechat", "opening_balance_minor": 600})
    debt = await create(app, "/debts", {"name": "朋友", "direction": "payable", "principal_minor": 300,
        "due_date": "2026-10-20", "installment_minor": 100})
    await request(app, "PATCH", "/debts/" + debt["id"], {"due_date": None, "note": "期初登记"})
    goal = await create(app, "/goals", {"name": "备用金", "target_minor": 100000, "prepared_minor": 1000})
    await request(app, "PATCH", "/goals/" + goal["id"], {"prepared_minor": 2000, "target_date": "2027-01-01"})
    await request(app, "PATCH", "/budget", {"budget_minor": 80000})
    await storage.close_private_workspace_storage()
    persisted = await request(app, "GET", "/state")
    assert persisted["budget_minor"] == 80000
    assert next(x for x in persisted["accounts"] if x["id"] == account["id"])["balance_minor"] == 600
    assert persisted["debts"][0]["remaining_minor"] == 300
    assert persisted["goals"][0]["prepared_minor"] == 2000
    report = await request(app, "GET", "/report" + PERIOD)
    assert report["income_minor"] == report["expense_minor"] == 0
    assert hashlib.sha256(app.business_path.read_bytes()).hexdigest() == digest
    with sqlite3.connect(app.business_path) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'private_%'").fetchall()
        assert db.execute("SELECT amount FROM finance_sentinel").fetchone()[0] == 70000
    with sqlite3.connect(app.private_path) as db:
        assert db.execute("SELECT COUNT(*) FROM private_pf_audits").fetchone()[0] >= 7


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [2, 3, 4, 5])
async def test_sales_other_admin_inactive_owner_denied(private_app, owner):
    for method, path, data in (("GET", "/state", None), ("POST", "/bootstrap", {}),
                                ("PATCH", "/budget", {"budget_minor": 100})):
        await request(private_app, method, path, data, expected=401 if owner == 5 else 403, owner=owner)


@pytest.mark.asyncio
async def test_owner_object_ids_never_cross_books(private_app, monkeypatch):
    app = private_app
    account, category, _ = await books(app)
    saved = await request(app, "POST", "/entries", entry(account, category=category), expected=201)
    monkeypatch.setenv("PRIVATE_WORKSPACE_OWNER_IDS", "1,2")
    await request(app, "POST", "/bootstrap", owner=2)
    for method, path, data in (
        ("PATCH", "/accounts/" + account["id"], {"name": "越权"}),
        ("PATCH", "/categories/" + category["id"], {"active": False}),
        ("POST", "/entries/" + saved["entry"]["id"] + "/void", None),
        ("POST", "/entries", entry(account, category=category)),
    ):
        await request(app, method, path, data, expected=404, owner=2)
    foreign = await request(app, "GET", "/entries" + PERIOD, owner=2)
    assert foreign["total"] == 0
    bad = await app.client.post(PREFIX + "/categories", headers=app.headers(),
        json={"name": "secret-private-text", "kind": "expense", "owner_id": "2"})
    assert bad.status_code == 422 and "secret-private-text" not in bad.text


@pytest.mark.asyncio
async def test_strict_validation_and_category_history(private_app):
    app = private_app
    account, expense, income = await books(app)
    for amount in (True, 1.5, "100", -1, 0, 9_000_000_000_001):
        await request(app, "POST", "/entries", entry(account, amount=amount, category=expense), expected=422)
    await request(app, "POST", "/entries", entry(account, category=income), expected=409)
    await request(app, "PATCH", "/categories/" + expense["id"], {"nullable": ["active"], "active": None}, expected=422)
    await request(app, "POST", "/entries", entry(account, category=expense, entry_date="1999-12-31"), expected=422)
    await request(app, "POST", "/entries", entry(account, category=expense, entry_date=1791763200), expected=422)
    await request(app, "GET", "/report?start_date=2000-01-01&end_date=2050-01-01", expected=422)
    await request(app, "GET", "/entries?start_date=2026-11-01&end_date=2026-10-01", expected=422)
    saved = await request(app, "POST", "/entries", entry(account, category=expense), expected=201)
    await request(app, "DELETE", "/categories/" + expense["id"], expected=409)
    await request(app, "PATCH", "/categories/" + expense["id"], {"kind": "income"}, expected=409)
    await request(app, "PATCH", "/categories/" + expense["id"], {"name": "改名保留历史", "active": False})
    await request(app, "POST", "/entries", entry(account, category=expense), expected=409)
    report = await request(app, "GET", "/report" + PERIOD)
    assert report["category_totals"] == [{"category_id": expense["id"], "name": "改名保留历史", "kind": "expense", "total_minor": 100, "count": 1}]
    await request(app, "PATCH", "/accounts/" + account["id"], {"opening_balance_minor": 200000}, expected=409)
    unused = await create(app, "/categories", {"name": "未使用", "kind": "expense"})
    assert await request(app, "DELETE", "/categories/" + unused["id"]) == {"deleted": True}
    assert saved["entry"]["amount_minor"] == 100


@pytest.mark.asyncio
async def test_creation_requires_key_and_rejects_unsupported_currency(private_app):
    app = private_app
    for body in ({}, {"client_request_id": None}, {"client_request_id": "not-a-uuid"}):
        await request(app, "POST", "/bootstrap", body, expected=422)
    assert (await request(app, "GET", "/state"))["initialized"] is False
    for path, body in (("/categories", {"name": "餐饮", "kind": "expense"}),
                        ("/accounts", {"name": "银行", "kind": "bank"}),
                        ("/debts", {"name": "朋友", "direction": "payable", "principal_minor": 100}),
                        ("/plans", {"name": "付款计划", "category_id": str(uuid4()), "amount_minor": 100, "due_date": "2026-10-20"}),
                        ("/goals", {"name": "储蓄", "target_minor": 100})):
        await request(app, "POST", path, body, expected=422)
    await request(app, "POST", "/accounts", {"name": "外币", "kind": "bank", "currency": "USD", "client_request_id": str(uuid4())}, expected=422)
    await request(app, "PATCH", "/budget", {"budget_minor": None, "nullable": ["budget_minor"]}, expected=422)


@pytest.mark.asyncio
async def test_request_receipt_lookup_is_private_and_reveals_no_money(private_app, monkeypatch):
    app = private_app
    account, expense, _ = await books(app)
    data = entry(account, category=expense, amount=4200)
    saved = await request(app, "POST", "/entries", data, expected=201)
    assert await request(app, "GET", "/requests/" + data["client_request_id"]) == {
        "found": True, "resource_kind": "entry", "entry_id": saved["entry"]["id"]}
    assert await request(app, "GET", "/requests/" + str(uuid4())) == {"found": False}
    debt_data = {"client_request_id": str(uuid4()), "name": "私人借款", "direction": "payable", "principal_minor": 1200}
    debt = await request(app, "POST", "/debts", debt_data, expected=201)
    assert await request(app, "GET", "/requests/" + debt_data["client_request_id"]) == {
        "found": True, "resource_kind": "debt", "resource_id": debt["id"]}
    monkeypatch.setenv("PRIVATE_WORKSPACE_OWNER_IDS", "1,2")
    assert await request(app, "GET", "/requests/" + data["client_request_id"], owner=2) == {"found": False}


@pytest.mark.asyncio
async def test_entry_and_entity_idempotency_never_double_counts(private_app):
    app = private_app
    account, expense, _ = await books(app)
    value = entry(account, category=expense, amount=600)
    responses = await asyncio.gather(*(request(app, "POST", "/entries", value, expected=201) for _ in range(5)))
    assert len({r["entry"]["id"] for r in responses}) == 1
    await request(app, "POST", "/entries", {**value, "amount_minor": 601}, expected=409)
    duplicate = {"name": "期初欠款", "direction": "payable", "principal_minor": 2000, "client_request_id": str(uuid4())}
    debts = await asyncio.gather(*(request(app, "POST", "/debts", duplicate, expected=201) for _ in range(3)))
    assert len({d["id"] for d in debts}) == 1
    await request(app, "POST", "/debts", {**duplicate, "principal_minor": 2001}, expected=409)
    await request(app, "POST", "/accounts", {"name": "复用key", "kind": "cash", "client_request_id": duplicate["client_request_id"]}, expected=409)
    await request(app, "POST", "/entries", {**value, "client_request_id": duplicate["client_request_id"]}, expected=409)
    state = await request(app, "GET", "/state")
    assert next(a for a in state["accounts"] if a["id"] == account["id"])["balance_minor"] == 99400
    assert len(state["debts"]) == 1


@pytest.mark.asyncio
async def test_category_reorder_is_atomic_and_owner_scoped(private_app, monkeypatch):
    app = private_app
    initial = await request(app, "POST", "/bootstrap")
    categories = [item for item in initial["categories"] if item["kind"] == "expense"]
    await request(app, "PATCH", "/categories/" + categories[0]["id"], {"active": False})
    ids = [item["id"] for item in reversed(categories)]
    reordered = await request(app, "POST", "/categories/reorder", {"kind": "expense", "category_ids": ids})
    assert [item["id"] for item in reordered["categories"]] == ids
    assert [item["sort_order"] for item in reordered["categories"]] == list(range(len(ids)))
    await request(app, "POST", "/categories/reorder", {"kind": "expense", "category_ids": ids[:-1]}, expected=409)
    await request(app, "POST", "/categories/reorder", {"kind": "expense", "category_ids": [*ids, ids[0]]}, expected=422)
    await request(app, "POST", "/categories/reorder", {"kind": "income", "category_ids": ids}, expected=409)
    monkeypatch.setenv("PRIVATE_WORKSPACE_OWNER_IDS", "1,2")
    await request(app, "POST", "/categories/reorder", {"kind": "expense", "category_ids": ids}, expected=409, owner=2)
    persisted = await request(app, "GET", "/state")
    assert [item["id"] for item in persisted["categories"] if item["kind"] == "expense"] == ids


@pytest.mark.asyncio
async def test_debt_direction_principal_and_concurrent_repayment(private_app):
    app = private_app
    account, expense, _ = await books(app, 10000)
    payable = await create(app, "/debts", {"name": "期初我欠", "direction": "payable", "principal_minor": 3000})
    receivable = await create(app, "/debts", {"name": "期初欠我", "direction": "receivable", "principal_minor": 1000})
    await request(app, "POST", "/entries", entry(account, "repay", 200, debt=receivable), expected=409)
    results = await asyncio.gather(*(app.client.post(PREFIX + "/entries", headers=app.headers(),
        json=entry(account, "repay", 2000, debt=payable)) for _ in range(2)))
    assert sorted(r.status_code for r in results) == [201, 409]
    outstanding = (await request(app, "GET", "/state"))["debts"]
    assert next(d for d in outstanding if d["id"] == payable["id"])["remaining_minor"] == 1000
    borrowed = await request(app, "POST", "/entries", entry(account, "borrow", 500, counterparty="新借款"), expected=201)
    borrow_debt = next(d for d in (await request(app, "GET", "/state"))["debts"] if d["id"] == borrowed["entry"]["debt_id"])
    await request(app, "POST", "/entries", entry(account, "repay", 200, debt=borrow_debt), expected=201)
    await request(app, "POST", "/entries/" + borrowed["entry"]["id"] + "/void", expected=409)
    await request(app, "POST", "/entries", entry(account, "collect", 500, debt=receivable), expected=201)
    report = await request(app, "GET", "/report" + PERIOD)
    assert report["income_minor"] == report["expense_minor"] == 0
    assert report["movements"] == {"borrow_minor": 500, "lend_minor": 0, "repay_minor": 2200, "collect_minor": 500, "transfer_minor": 0}


@pytest.mark.asyncio
async def test_transfer_void_restore_and_impossible_reversal_roll_back(private_app):
    app = private_app
    account, expense, income = await books(app, 1000)
    other = await create(app, "/accounts", {"name": "支付宝", "kind": "alipay"})
    transferred = await request(app, "POST", "/entries", entry(account, "transfer", 600, to_account_id=other["id"]), expected=201)
    await request(app, "POST", "/entries", entry(account, "transfer", 500, to_account_id=other["id"]), expected=409)
    spent = await request(app, "POST", "/entries", entry(other, amount=500, category=expense), expected=201)
    await request(app, "POST", "/entries/" + transferred["entry"]["id"] + "/void", expected=409)
    await request(app, "POST", "/entries/" + spent["entry"]["id"] + "/void")
    await request(app, "POST", "/entries/" + transferred["entry"]["id"] + "/void")
    await request(app, "POST", "/entries/" + spent["entry"]["id"] + "/restore", expected=409)
    await request(app, "POST", "/entries/" + transferred["entry"]["id"] + "/restore")
    await request(app, "POST", "/entries/" + spent["entry"]["id"] + "/restore")
    state = await request(app, "GET", "/state")
    assert sum(a["balance_minor"] for a in state["accounts"]) == 500
    assert (await request(app, "GET", "/report" + PERIOD))["expense_minor"] == 500
    await request(app, "PATCH", "/entries/" + spent["entry"]["id"], {"note": "修正说明", "entry_date": "2026-10-11"})
    await request(app, "PATCH", "/entries/" + spent["entry"]["id"], {"amount_minor": 300}, expected=422)


@pytest.mark.asyncio
async def test_plan_payment_actual_date_once_and_safe_restore(private_app):
    app = private_app
    account, expense, _ = await books(app, 10000)
    plan = await create(app, "/plans", {"name": "物业费", "category_id": expense["id"], "amount_minor": 2000, "due_date": "2026-10-20"})
    assert (await request(app, "GET", "/report" + PERIOD))["expense_minor"] == 0
    data = {"account_id": account["id"], "amount_minor": 1800, "entry_date": "2026-10-12", "client_request_id": str(uuid4())}
    paid = await request(app, "POST", "/plans/" + plan["id"] + "/pay", data)
    assert await request(app, "POST", "/plans/" + plan["id"] + "/pay", data) == paid
    await request(app, "POST", "/plans/" + plan["id"] + "/pay", {**data, "client_request_id": str(uuid4())}, expected=409)
    current = (await request(app, "GET", "/state"))["plans"][0]
    assert current["actual_minor"] == 1800 and current["paid_date"] == "2026-10-12" and current["amount_minor"] == 2000
    await request(app, "PATCH", "/plans/" + plan["id"], {"amount_minor": 2200}, expected=409)
    await request(app, "POST", "/entries/" + paid["entry"]["id"] + "/void")
    assert (await request(app, "GET", "/state"))["plans"][0]["status"] == "pending"
    await request(app, "POST", "/entries/" + paid["entry"]["id"] + "/restore")
    assert (await request(app, "GET", "/report" + PERIOD))["expense_minor"] == 1800
    await request(app, "POST", "/entries/" + paid["entry"]["id"] + "/void")
    second = await request(app, "POST", "/plans/" + plan["id"] + "/pay", {**data, "client_request_id": str(uuid4())})
    await request(app, "POST", "/entries/" + paid["entry"]["id"] + "/restore", expected=409)
    assert (await request(app, "GET", "/state"))["plans"][0]["paid_entry_id"] == second["entry"]["id"]


@pytest.mark.asyncio
async def test_paid_plan_category_stays_consistent_with_ledger(private_app):
    app = private_app
    account, expense, _ = await books(app)
    other = await create(app, "/categories", {"name": "实际住房支出", "kind": "expense"})
    plan = await create(app, "/plans", {"name": "计划", "category_id": expense["id"], "amount_minor": 1000, "due_date": "2026-10-20"})
    result = await request(app, "POST", "/plans/" + plan["id"] + "/pay", {
        "account_id": account["id"], "amount_minor": 900, "entry_date": "2026-10-12", "client_request_id": str(uuid4())})
    identity = result["entry"]["id"]
    await request(app, "PATCH", "/entries/" + identity, {"category_id": other["id"], "entry_date": "2026-10-11"})
    current = (await request(app, "GET", "/state"))["plans"][0]
    assert current["category_id"] == other["id"] and current["paid_date"] == "2026-10-11"
    await request(app, "POST", "/entries/" + identity + "/void")
    await request(app, "PATCH", "/plans/" + plan["id"], {"category_id": expense["id"]})
    await request(app, "POST", "/entries/" + identity + "/restore")
    assert (await request(app, "GET", "/state"))["plans"][0]["category_id"] == other["id"]
    assert (await request(app, "GET", "/report" + PERIOD))["category_totals"][0]["category_id"] == other["id"]


@pytest.mark.asyncio
async def test_inactive_existing_category_allows_metadata_updates(private_app):
    app = private_app
    account, expense, _ = await books(app)
    plan = await create(app, "/plans", {"name": "原计划", "category_id": expense["id"], "amount_minor": 1000, "due_date": "2026-10-20"})
    saved = await request(app, "POST", "/entries", entry(account, category=expense), expected=201)
    await request(app, "PATCH", "/categories/" + expense["id"], {"active": False})
    changed_plan = await request(app, "PATCH", "/plans/" + plan["id"], {
        "category_id": expense["id"], "due_date": "2026-10-25"})
    assert changed_plan["due_date"] == "2026-10-25"
    changed_entry = await request(app, "PATCH", "/entries/" + saved["entry"]["id"], {
        "category_id": expense["id"], "note": "只改备注"})
    assert changed_entry["entry"]["note"] == "只改备注"
    inactive = await create(app, "/categories", {"name": "另一个停用类别", "kind": "expense", "active": False})
    for path in ("/plans/" + plan["id"], "/entries/" + saved["entry"]["id"]):
        await request(app, "PATCH", path, {"category_id": inactive["id"]}, expected=409)


@pytest.mark.asyncio
async def test_concurrent_plan_payment_and_transfer_only_once(private_app):
    app = private_app
    account, expense, _ = await books(app, 1000)
    plan = await create(app, "/plans", {"name": "计划", "category_id": expense["id"], "amount_minor": 100, "due_date": "2026-10-20"})
    async def pay():
        return await app.client.post(PREFIX + "/plans/" + plan["id"] + "/pay", headers=app.headers(), json={
            "account_id": account["id"], "amount_minor": 100, "entry_date": "2026-10-12", "client_request_id": str(uuid4())})
    assert sorted(r.status_code for r in await asyncio.gather(pay(), pay())) == [200, 409]
    target = await create(app, "/accounts", {"name": "转入", "kind": "cash"})
    responses = await asyncio.gather(*(app.client.post(PREFIX + "/entries", headers=app.headers(),
        json=entry(account, "transfer", 600, to_account_id=target["id"])) for _ in range(2)))
    assert sorted(r.status_code for r in responses) == [201, 409]
    state = await request(app, "GET", "/state")
    assert next(a for a in state["accounts"] if a["id"] == account["id"])["balance_minor"] == 300
    assert next(a for a in state["accounts"] if a["id"] == target["id"])["balance_minor"] == 600


@pytest.mark.asyncio
async def test_report_covers_all_pages_and_uses_transaction_dates(private_app):
    app = private_app
    account, expense, income = await books(app, 100000)
    for amount in range(1, 66):
        await request(app, "POST", "/entries", entry(account, amount=amount, category=expense), expected=201)
    await request(app, "POST", "/entries", entry(account, "income", 12345, category=income), expected=201)
    await request(app, "POST", "/entries", entry(account, amount=999, category=expense, entry_date="2026-09-30"), expected=201)
    listing = await request(app, "GET", "/entries" + PERIOD + "&page_size=20&page=1")
    assert listing["total"] == 66 and len(listing["items"]) == 20
    result = await request(app, "GET", "/report" + PERIOD)
    assert result["expense_minor"] == sum(range(1, 66))
    assert result["income_minor"] == 12345 and result["net_minor"] == 12345 - sum(range(1, 66))
    assert result["trend"] == [{"date": "2026-10-12", "income_minor": 12345, "expense_minor": sum(range(1, 66))}]
    saved = listing["items"][0]
    await request(app, "POST", "/entries/" + saved["id"] + "/void")
    assert (await request(app, "GET", "/entries" + PERIOD + "&status=all"))["total"] == 66
    assert (await request(app, "GET", "/entries" + PERIOD + "&status=void"))["total"] == 1


@pytest.mark.asyncio
async def test_separate_processes_cannot_overdraw_same_account(private_app):
    app = private_app
    account, expense, _ = await books(app, 1000)
    script = (
        "import asyncio,json,sys; from fastapi import HTTPException; "
        "from services.private_workspace import private_session_factory; "
        "from services.private_personal_finance import create_entry; "
        "from schemas.private_personal_finance import EntryCreate; "
        "exec('async def run():\\n sessions=await private_session_factory()\\n async with sessions() as db:\\n"
        "  try:\\n   await create_entry(db,\"1\",EntryCreate.model_validate(json.loads(sys.argv[1])))\\n   print(201)\\n"
        "  except HTTPException as error:\\n   print(error.status_code)'); asyncio.run(run())"
    )
    cwd = str(Path(__file__).parents[1])
    async def child():
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", script,
            json.dumps(entry(account, category=expense, amount=700)), cwd=cwd, env=os.environ.copy(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        assert process.returncode == 0, stderr.decode()
        return int(stdout.decode().strip())
    assert sorted(await asyncio.gather(child(), child())) == [201, 409]
    state = await request(app, "GET", "/state")
    assert next(a for a in state["accounts"] if a["id"] == account["id"])["balance_minor"] == 300
