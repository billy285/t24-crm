import asyncio
import csv
import io
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.merchant_import_batches import MerchantImportBatch
from models.merchant_ai_analyses import MerchantAiAnalyses
from models.merchant_pool import MerchantPool
from models.sales_leads import SalesLeads
from schemas.auth import UserResponse

HEADERS = ["商家名称", "商家电话", "商家位置", "地区", "来源"]


def auth(role="sales_manager", employee_id=10):
    token = create_access_token({"emp_id": employee_id, "email": f"{employee_id}@example.com", "role": role, "name": f"Manager {employee_id}"})
    return {"Authorization": f"Bearer {token}"}


def csv_file(rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


GOOD = ["Sample Cafe", "+1 212-555-0123", "1 Main St", "New York, NY, US", "Google Maps"]


def source_csv(rows, optional_headers=("行业", "来源URL", "来源日期", "核验类型")):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([*HEADERS, *optional_headers])
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


@pytest_asyncio.fixture
async def imports_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        yield client, maker
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


async def preview(client, rows, headers=None):
    response = await client.post("/api/v1/merchant-imports/preview", headers=headers or auth(), files={"file": ("merchants.csv", csv_file(rows), "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


async def count(maker, model):
    async with maker() as session:
        return await session.scalar(select(func.count()).select_from(model))


@pytest.mark.asyncio
async def test_preview_preserves_original_lines_and_never_creates_business_records(imports_client):
    client, maker = imports_client
    batch = await preview(client, [GOOD, [], ["Bad Phone", "123", "", "", ""], ["", "+1 415-555-0123", "", "", ""], ["Repeated Cafe", "+1 (212) 555-0123 ext 9", "2 Main St", "New York, NY, US", "Maps"]])
    assert [row["row"] for row in batch["rows"]] == [2, 4, 5, 6]
    assert [row["status"] for row in batch["rows"]] == ["pending", "no_phone", "error", "duplicate"]
    assert batch["rows"][0]["normalized_phone"] == "+12125550123"
    assert batch["summary"] == {"pending": 1, "isolated": 2, "errors": 1, "importable": 3}
    assert await count(maker, MerchantPool) == 0
    assert await count(maker, SalesLeads) == 0
    assert await count(maker, MerchantImportBatch) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("region,state,zone", [
    ("NY, US", "NY", "America/New_York"),
    ("California, USA", "CA", "America/Los_Angeles"),
    ("TX, US", "TX", None),
])
async def test_state_only_csv_preserves_missing_city_and_conservative_timezone(imports_client, region, state, zone):
    from services.sales_timezones import resolve_contact_timezone

    client, maker = imports_client
    batch = await preview(client, [["店名待核验｜中文门店招聘", GOOD[1], "街道地址待核验", region, "中文招聘待核验"]])
    assert batch["summary"] == {"pending": 1, "isolated": 0, "errors": 0, "importable": 1}
    confirmed = await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    assert confirmed.status_code == 200, confirmed.text
    async with maker() as session:
        row = (await session.execute(select(MerchantPool))).scalar_one()
        assert (row.country, row.state, row.city) == ("US", state, None)
        timezone = resolve_contact_timezone(country=row.country, state=row.state, city=row.city, address=row.address)
        assert timezone["timezone"] == zone
        assert timezone["timezone_needs_confirmation"] is True


@pytest.mark.asyncio
async def test_confirm_uses_server_validation_and_retry_never_duplicates(imports_client):
    client, maker = imports_client
    batch = await preview(client, [GOOD, ["Bad Phone", "123", "", "", "Maps"], ["Duplicate", GOOD[1], "2 Main St", GOOD[3], "Maps"]])
    response = await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth(), json={"rows": [{"status": "pending", "phone_verified": True}]})
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "committed"
    assert [row["status"] for row in receipt["rows"]] == ["pending", "no_phone", "duplicate"]
    retry = await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    assert retry.status_code == 200
    assert await count(maker, MerchantPool) == 3
    assert await count(maker, SalesLeads) == 0
    async with maker() as session:
        rows = (await session.execute(select(MerchantPool).order_by(MerchantPool.id))).scalars().all()
        assert rows[0].phone == GOOD[1]
        assert rows[2].duplicate_of_id == rows[0].id
        assert rows[1].isolation_reason


@pytest.mark.asyncio
async def test_confirmation_rechecks_leads_created_after_preview(imports_client):
    client, maker = imports_client
    batch = await preview(client, [GOOD])
    assert batch["rows"][0]["status"] == "pending"
    async with maker() as session:
        session.add(SalesLeads(business_name="Existing Manual Lead", phone=GOOD[1], country="US"))
        await session.commit()
    response = await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    assert response.status_code == 200
    assert response.json()["rows"][0]["status"] == "duplicate"
    assert "销售线索" in response.json()["rows"][0]["reason"]
    assert await count(maker, SalesLeads) == 1


@pytest.mark.asyncio
async def test_duplicate_upload_reuses_visible_receipt_and_preserves_manager_scope(imports_client):
    client, maker = imports_client
    batch = await preview(client, [GOOD])
    same = await preview(client, [GOOD])
    assert same["id"] == batch["id"] and same["duplicate_upload"]
    await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    committed = await preview(client, [GOOD])
    assert committed["id"] == batch["id"] and committed["status"] == "committed"
    other = await client.get(f"/api/v1/merchant-imports/{batch['id']}", headers=auth(employee_id=20))
    assert other.status_code == 404
    assert (await client.get("/api/v1/merchant-imports", headers=auth(employee_id=20))).json()["items"] == []
    assert (await client.get(f"/api/v1/merchant-imports/{batch['id']}/errors.csv", headers=auth(employee_id=20))).status_code == 404
    assert (await client.post(f"/api/v1/merchant-imports/{batch['id']}/revert", headers=auth(employee_id=20))).status_code == 404
    assert (await client.get("/api/v1/merchant-imports", headers=auth("admin", 1))).json()["items"][0]["id"] == batch["id"]
    assert (await client.get("/api/v1/merchant-imports", headers=auth("sales", 11))).status_code == 403
    assert (await client.post("/api/v1/merchant-imports/preview", headers=auth("sales", 11), files={"file": ("merchants.csv", csv_file([GOOD]), "text/csv")})).status_code == 403
    assert await count(maker, MerchantPool) == 1


@pytest.mark.asyncio
async def test_unmodified_batch_can_be_reverted_and_receipt_retained(imports_client):
    client, maker = imports_client
    batch = await preview(client, [GOOD, ["Duplicate", GOOD[1], "", GOOD[3], "Maps"]])
    await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    response = await client.post(f"/api/v1/merchant-imports/{batch['id']}/revert", headers=auth())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "reverted"
    assert await count(maker, MerchantPool) == 0
    assert await count(maker, MerchantImportBatch) == 1
    assert (await client.post(f"/api/v1/merchant-imports/{batch['id']}/revert", headers=auth())).status_code == 200
    assert (await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())).status_code == 409
    next_batch = await preview(client, [GOOD, ["Duplicate", GOOD[1], "", GOOD[3], "Maps"]])
    assert next_batch["id"] != batch["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["edited", "converted", "linked", "analyzed", "referenced", "deleted"])
async def test_revert_with_any_later_change_is_atomic_and_preserves_records(imports_client, change):
    client, maker = imports_client
    batch = await preview(client, [GOOD, ["Second Cafe", "+1 415-555-0123", "2 Main St", "San Francisco, CA, US", "Maps"]])
    await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    async with maker() as session:
        merchant = (await session.execute(select(MerchantPool).order_by(MerchantPool.id))).scalars().first()
        if change == "edited":
            merchant.contact_name = "Changed after import"
        elif change == "converted":
            merchant.pool_status = "converted"
            merchant.converted_lead_id = 999
        elif change == "linked":
            session.add(SalesLeads(business_name=merchant.business_name, phone=merchant.phone, merchant_pool_id=merchant.id))
        elif change == "analyzed":
            session.add(MerchantAiAnalyses(merchant_id=merchant.id, analysis_json="{}", source_snapshot="{}"))
        elif change == "referenced":
            session.add(MerchantPool(business_name="Later Duplicate", phone=merchant.phone, pool_status="duplicate", duplicate_of_id=merchant.id, data_source="api"))
        else:
            await session.delete(merchant)
        await session.commit()
    before = await count(maker, MerchantPool)
    response = await client.post(f"/api/v1/merchant-imports/{batch['id']}/revert", headers=auth())
    assert response.status_code == 409
    assert response.json()["detail"]["rows"] == [2]
    assert await count(maker, MerchantPool) == before
    receipt = await client.get(f"/api/v1/merchant-imports/{batch['id']}", headers=auth())
    assert receipt.json()["status"] == "committed"


@pytest.mark.asyncio
async def test_repeat_preview_keeps_committed_undo_snapshot_and_later_batch_reference(imports_client):
    client, maker = imports_client
    first = await preview(client, [GOOD])
    response = await client.post(f"/api/v1/merchant-imports/{first['id']}/confirm", headers=auth())
    first_merchant_id = response.json()["rows"][0]["merchant_id"]
    repeated = await preview(client, [GOOD])
    assert repeated["status"] == "committed"
    assert repeated["rows"][0]["merchant_id"] == first_merchant_id
    second = await preview(client, [["Later Duplicate", GOOD[1], "2 Main St", GOOD[3], "Maps"]])
    response = await client.post(f"/api/v1/merchant-imports/{second['id']}/confirm", headers=auth())
    assert response.status_code == 200
    assert response.json()["rows"][0]["status"] == "duplicate"
    async with maker() as session:
        merchant = await session.get(MerchantPool, response.json()["rows"][0]["merchant_id"])
        assert merchant.duplicate_of_id == first_merchant_id
    blocked = await client.post(f"/api/v1/merchant-imports/{first['id']}/revert", headers=auth())
    assert blocked.status_code == 409
    assert await count(maker, MerchantPool) == 2
    assert (await client.post(f"/api/v1/merchant-imports/{second['id']}/revert", headers=auth())).status_code == 200
    assert (await client.post(f"/api/v1/merchant-imports/{first['id']}/revert", headers=auth())).status_code == 200
    assert await count(maker, MerchantPool) == 0


@pytest.mark.asyncio
async def test_confirm_storage_failure_rolls_back_whole_batch_and_can_retry(imports_client, monkeypatch):
    client, maker = imports_client
    batch = await preview(client, [GOOD, ["Second Cafe", "+1 415-555-0123", "2 Main St", "San Francisco, CA, US", "Maps"]])
    original_flush = AsyncSession.flush
    merchant_flushes = 0

    async def failing_flush(session, objects=None):
        nonlocal merchant_flushes
        if any(isinstance(item, MerchantPool) for item in session.new):
            merchant_flushes += 1
            if merchant_flushes == 2:
                raise RuntimeError("simulated storage failure after first merchant")
        return await original_flush(session, objects)

    monkeypatch.setattr(AsyncSession, "flush", failing_flush)
    failed = await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    assert failed.status_code == 500
    assert await count(maker, MerchantPool) == 0
    assert (await client.get(f"/api/v1/merchant-imports/{batch['id']}", headers=auth())).json()["status"] == "preview"
    monkeypatch.setattr(AsyncSession, "flush", original_flush)
    retried = await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    assert retried.status_code == 200
    assert await count(maker, MerchantPool) == 2


async def legacy_import(client, mode, records):
    if mode == "csv":
        return await client.post("/api/v1/merchant-pool/import-csv", headers=auth(), files={"file": ("legacy.csv", csv_file(records), "text/csv")})
    return await client.post("/api/v1/merchant-pool/import", headers=auth(), json={"data_source": "compat", "records": [dict(zip(("business_name", "phone", "address", "region"), record[:4])) for record in records]})


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["json", "csv"])
async def test_legacy_import_keeps_compatible_response_and_reserves_batch_reference(imports_client, mode):
    client, maker = imports_client
    batch = await preview(client, [GOOD])
    response = await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    original_id = response.json()["rows"][0]["merchant_id"]
    imported = await legacy_import(client, mode, [["Legacy Duplicate", GOOD[1], "2 Main St", GOOD[3], "Maps"]])
    assert imported.status_code == 200, imported.text
    data = imported.json()
    assert data["total"] == 1
    assert data["counts"]["duplicate"] == 1
    assert data["errors"] == []
    if mode == "csv":
        assert data["template_headers"] == HEADERS
    else:
        assert data["items"][0]["duplicate_of_id"] == original_id
    async with maker() as session:
        legacy = (await session.execute(select(MerchantPool).where(MerchantPool.id != original_id))).scalar_one()
        assert legacy.duplicate_of_id == original_id
    assert (await client.post(f"/api/v1/merchant-imports/{batch['id']}/revert", headers=auth())).status_code == 409
    assert await count(maker, MerchantPool) == 2
    assert await count(maker, SalesLeads) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["json", "csv"])
async def test_legacy_reference_changes_abort_entire_request_without_success_receipt(imports_client, monkeypatch, mode):
    client, maker = imports_client
    async with maker() as session:
        session.add_all([
            MerchantPool(id=30, business_name="Existing Target", phone=GOOD[1], country="US", data_source="test"),
            MerchantPool(id=31, business_name="Other Target", phone="+1 646-555-0123", country="US", data_source="test"),
        ])
        await session.commit()
    from routers import merchant_pool
    original_classify = merchant_pool._classify_record
    checks = 0

    async def changed_target(db, record, exclude_id=None):
        nonlocal checks
        if record.business_name == "Changed Reference":
            checks += 1
            return "duplicate", "identity changed while waiting", 30 if checks == 1 else 31, None
        return await original_classify(db, record, exclude_id)

    monkeypatch.setattr(merchant_pool, "_classify_record", changed_target)
    response = await legacy_import(client, mode, [
        ["Independent Cafe", "+1 415-555-0123", "2 Main St", "San Francisco, CA, US", "Maps"],
        ["Changed Reference", GOOD[1], "1 Main St", GOOD[3], "Maps"],
    ])
    assert response.status_code == 409, response.text
    assert "本次操作尚未写入" in response.json()["detail"]
    assert await count(maker, MerchantPool) == 2
    assert await count(maker, SalesLeads) == 0


@pytest.mark.asyncio
async def test_cleaning_existing_record_reserves_duplicate_reference_before_batch_undo(imports_client):
    client, maker = imports_client
    batch = await preview(client, [GOOD])
    confirmed = await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    original_id = confirmed.json()["rows"][0]["merchant_id"]
    created = await legacy_import(client, "json", [["Needs Cleaning", "123", "2 Main St", GOOD[3], "Maps"]])
    other_id = created.json()["items"][0]["id"]
    cleaned = await client.put(f"/api/v1/merchant-pool/{other_id}", headers=auth(), json={"phone": GOOD[1], "contact_name": "Owner"})
    assert cleaned.status_code == 200, cleaned.text
    assert cleaned.json()["pool_status"] == "duplicate"
    assert cleaned.json()["duplicate_of_id"] == original_id
    blocked = await client.post(f"/api/v1/merchant-imports/{batch['id']}/revert", headers=auth())
    assert blocked.status_code == 409
    assert await count(maker, MerchantPool) == 2


@pytest.mark.asyncio
async def test_cleaning_reference_conflict_preserves_all_original_fields_and_batch(imports_client, monkeypatch):
    client, maker = imports_client
    batch = await preview(client, [GOOD])
    confirmed = await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    original_id = confirmed.json()["rows"][0]["merchant_id"]
    async with maker() as session:
        editable = MerchantPool(business_name="Original Prospect", phone="123", country="US", contact_name="Before", data_source="test", pool_status="no_phone", created_by_id=10)
        session.add(editable)
        await session.commit()
        other_id = editable.id
    from routers import merchant_pool
    checks = 0

    async def changed_target(db, record, exclude_id=None):
        nonlocal checks
        checks += 1
        return "duplicate", "identity changed while waiting", original_id if checks == 1 else other_id, None

    monkeypatch.setattr(merchant_pool, "_classify_record", changed_target)
    response = await client.put(f"/api/v1/merchant-pool/{other_id}", headers=auth(), json={"business_name": "Changed Name", "phone": GOOD[1], "contact_name": "Changed Owner", "address": "Changed address"})
    assert response.status_code == 409, response.text
    async with maker() as session:
        unchanged = await session.get(MerchantPool, other_id)
        assert unchanged.business_name == "Original Prospect"
        assert unchanged.phone == "123"
        assert unchanged.contact_name == "Before"
        assert unchanged.address is None
        assert unchanged.pool_status == "no_phone"
        assert unchanged.duplicate_of_id is None
    assert (await client.get(f"/api/v1/merchant-imports/{batch['id']}", headers=auth())).json()["status"] == "committed"
    assert await count(maker, MerchantPool) == 2


@pytest.mark.asyncio
async def test_errors_download_keeps_original_rows_and_escapes_excel_formulas(imports_client):
    client, _ = imports_client
    batch = await preview(client, [GOOD, [], ["=HYPERLINK(test)", "123", "", "", "Maps"], ["", "", "", "", ""]])
    response = await client.get(f"/api/v1/merchant-imports/{batch['id']}/errors.csv", headers=auth())
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0] == ["原始行号", *HEADERS, "处理结果", "原因"]
    assert rows[1][0] == "4"
    assert rows[1][1] == "'=HYPERLINK(test)"


@pytest.mark.asyncio
async def test_excel_and_international_places_do_not_guess_us(imports_client):
    client, _ = imports_client
    workbook = Workbook()
    workbook.active.append(HEADERS)
    workbook.active.append(["Canadian Cafe", "647-555-0123", "1 King St", "Toronto, ON, Canada", "Maps"])
    workbook.active.append([None] * 5)
    workbook.active.append(["Unclear Country", "212-555-0123", "1 Main St", "New York, NY", "Maps"])
    data = io.BytesIO()
    workbook.save(data)
    response = await client.post("/api/v1/merchant-imports/preview", headers=auth(), files={"file": ("merchants.xlsx", data.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert [row["row"] for row in rows] == [2, 4]
    assert rows[0]["status"] == "pending"
    assert rows[0]["normalized_phone"] == "+16475550123"
    assert rows[0]["phone_country"] == "CA"
    assert rows[1]["status"] == "no_phone"
    assert rows[1]["phone_status"] == "needs_country"


@pytest.mark.asyncio
async def test_wrong_headers_limit_and_all_errors_never_write_merchants(imports_client):
    client, maker = imports_client
    for filename, content in [("other.xls", b"bad"), ("wrong.csv", b"name,phone\nCafe,123\n"), ("large.csv", csv_file([GOOD] * 2001))]:
        response = await client.post("/api/v1/merchant-imports/preview", headers=auth(), files={"file": (filename, content, "text/csv")})
        assert response.status_code == 400
    assert await count(maker, MerchantImportBatch) == 0
    batch = await preview(client, [["", "123", "", "", "Maps"]])
    response = await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    assert response.status_code == 400
    assert await count(maker, MerchantPool) == 0
    assert (await client.get(f"/api/v1/merchant-imports/{batch['id']}", headers=auth())).json()["status"] == "preview"


@pytest_asyncio.fixture
async def file_imports_db(tmp_path):
    # Separate file-backed connections exercise real SQLite write locking; WAL
    # permits concurrent readers, so SELECT/FOR UPDATE alone is insufficient.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'imports.db'}", poolclass=NullPool, connect_args={"timeout": 0.08})
    async with engine.connect() as connection:
        await connection.execute(text("PRAGMA journal_mode=WAL"))
        await connection.commit()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["legacy", "batch"])
@pytest.mark.parametrize("first", ["duplicate", "undo"])
async def test_two_connection_sqlite_undo_reference_race_never_orphans_or_rewrites_history(file_imports_db, monkeypatch, source, first):
    from routers.merchant_pool import MerchantRecord, _store_record
    from services import merchant_imports
    from services.merchant_row_locks import lock_merchant_rows

    maker = file_imports_db
    user = UserResponse(id="10", email="10@example.com", name="Manager 10", role="sales_manager")
    async with maker() as session:
        historical = MerchantPool(id=100, business_name="Historical Archive", phone="+1 647-555-0123 ext 7", country="CA", city="Toronto", contact_name="Original Owner", data_source="original-source", pool_status="archived", raw_payload='{"unaltered":"证据"}')
        session.add(historical)
        await session.commit()
    async with maker() as session:
        first_batch = await merchant_imports.preview_import(session, user, "original.csv", csv_file([GOOD]))
        committed = await merchant_imports.confirm_import(session, user, first_batch["id"])
        original_id = committed["rows"][0]["merchant_id"]
    async with maker() as session:
        original_snapshot = merchant_imports.merchant_snapshot(await session.get(MerchantPool, original_id))
        historical_snapshot = merchant_imports.merchant_snapshot(await session.get(MerchantPool, 100))
        if source == "batch":
            later_batch = await merchant_imports.preview_import(session, user, "later.csv", csv_file([["Later Duplicate", GOOD[1], "2 Main St", GOOD[3], "Maps"]]))

    held, release = asyncio.Event(), asyncio.Event()
    real_lock = lock_merchant_rows

    async def pause_batch_lock(db, ids):
        rows = await real_lock(db, ids)
        if ids and not held.is_set():
            held.set()
            await asyncio.wait_for(release.wait(), timeout=5)
        return rows

    if first == "undo" or source == "batch":
        monkeypatch.setattr(merchant_imports, "lock_merchant_rows", pause_batch_lock)

    async def create_reference(*, pause=False):
        async with maker() as session:
            if source == "batch":
                return await merchant_imports.confirm_import(session, user, later_batch["id"])
            record = await _store_record(session, MerchantRecord(business_name="Later Duplicate", phone=GOOD[1], country="US", address="2 Main St"), "compat", user)
            if pause:
                held.set()
                await asyncio.wait_for(release.wait(), timeout=5)
            merchant_id, duplicate_id, status = record.id, record.duplicate_of_id, record.pool_status
            await session.commit()
            return {"id": merchant_id, "duplicate_of_id": duplicate_id, "status": status}

    async def undo():
        async with maker() as session:
            return await merchant_imports.revert_import(session, user, first_batch["id"])

    writer = asyncio.create_task(create_reference(pause=True) if first == "duplicate" else undo())
    await asyncio.wait_for(held.wait(), timeout=5)
    try:
        with pytest.raises(HTTPException) as conflict:
            await (undo() if first == "duplicate" else create_reference())
        assert conflict.value.status_code == 409
        assert "稍后重试" in conflict.value.detail
    finally:
        release.set()
    await asyncio.wait_for(writer, timeout=5)
    # Finish the losing operation after its explicit rollback/retry. A reference
    # wins => undo is blocked; undo wins => a new prospect has no deleted target.
    if first == "duplicate":
        with pytest.raises(HTTPException) as blocked:
            await undo()
        assert blocked.value.status_code == 409
    else:
        async with maker() as session:
            assert await session.get(MerchantPool, original_id) is None
        await create_reference()

    async with maker() as session:
        history = await session.get(MerchantPool, 100)
        assert merchant_imports.merchant_snapshot(history) == historical_snapshot
        original = await session.get(MerchantPool, original_id)
        later = (await session.execute(select(MerchantPool).where(MerchantPool.business_name == "Later Duplicate"))).scalar_one()
        receipt = await session.get(MerchantImportBatch, first_batch["id"])
        saved = json.loads(receipt.result_json)[0]
        assert saved["snapshot"] == original_snapshot
        assert saved["raw"]["商家电话"] == GOOD[1]
        if first == "duplicate":
            assert original is not None
            assert merchant_imports.merchant_snapshot(original) == original_snapshot
            assert later.duplicate_of_id == original_id
            assert receipt.status == "committed"
        else:
            # The legacy SQLite table may reuse a deleted integer ID. Prove the
            # old row was removed before retry above, then check the new identity.
            assert original is None or original.id == later.id
            assert await session.scalar(select(func.count()).select_from(MerchantPool).where(MerchantPool.business_name == GOOD[0])) == 0
            assert later.duplicate_of_id is None
            assert later.pool_status == "pending"
            assert receipt.status == "reverted"
        all_ids = set((await session.execute(select(MerchantPool.id))).scalars().all())
        assert not (set((await session.execute(select(MerchantPool.duplicate_of_id).where(MerchantPool.duplicate_of_id.isnot(None)))).scalars().all()) - all_ids)
        assert await session.scalar(select(func.count()).select_from(SalesLeads)) == 0


@pytest.mark.asyncio
async def test_extended_source_metadata_and_industry_survive_atomic_import_and_undo(imports_client):
    client, maker = imports_client
    content = source_csv([[*GOOD, 'nail salon', 'https://example.com/business/123', '2026-11-01', '招聘联系点']])
    response = await client.post('/api/v1/merchant-imports/preview', headers=auth(), data={'default_industry': '餐厅'}, files={'file': ('source.csv', content, 'text/csv')})
    assert response.status_code == 200, response.text
    batch = response.json()
    assert batch['template_headers'] == [*HEADERS, '行业', '来源URL', '来源日期', '核验类型']
    assert batch['import_defaults'] == {'industry': '餐厅'}
    assert batch['rows'][0]['source_metadata'] == {'source_url': 'https://example.com/business/123', 'source_date': '2026-11-01', 'verification_type': 'recruitment_contact'}
    assert await count(maker, MerchantPool) == 0
    result = await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())
    assert result.status_code == 200, result.text
    async with maker() as session:
        row = (await session.execute(select(MerchantPool))).scalar_one()
        assert row.industry == '美业'
        raw = json.loads(row.raw_payload)
        assert raw['来源日期'] == '2026-11-01'
        assert raw['prospect_source'] == batch['rows'][0]['source_metadata']
        assert raw['prospect_quality']['status'] == 'pending'
    listing = await client.get('/api/v1/merchant-pool?quality_status=pending', headers=auth())
    assert listing.status_code == 200, listing.text
    assert listing.json()['total'] == 1
    assert listing.json()['items'][0]['prospect_quality']['status'] == 'pending'
    assert listing.json()['items'][0]['prospect_source']['source_url'] == 'https://example.com/business/123'
    assert (await client.get('/api/v1/merchant-pool?quality_status=valid', headers=auth())).json()['total'] == 0
    assert (await client.post(f"/api/v1/merchant-imports/{batch['id']}/revert", headers=auth())).status_code == 200
    assert await count(maker, MerchantPool) == 0


@pytest.mark.asyncio
async def test_default_industry_is_frozen_on_duplicate_upload_and_confirm(imports_client):
    client, maker = imports_client
    async def with_industry(value):
        return await client.post('/api/v1/merchant-imports/preview', headers=auth(), data={'default_industry': value}, files={'file': ('old-five.csv', csv_file([GOOD]), 'text/csv')})
    first = (await with_industry('美业')).json()
    repeated = (await with_industry('餐厅')).json()
    assert repeated['id'] == first['id'] and repeated['duplicate_upload']
    assert repeated['import_defaults'] == {'industry': '美业'}
    assert (await client.post(f"/api/v1/merchant-imports/{first['id']}/confirm", headers=auth(), json={'default_industry': '餐厅'})).status_code == 200
    async with maker() as session:
        assert (await session.execute(select(MerchantPool))).scalar_one().industry == '美业'


@pytest.mark.asyncio
@pytest.mark.parametrize('extras,reason', [
    (['美业', 'javascript:alert(1)', '2026-11-01', '公开商家资料'], '来源URL'),
    (['美业', 'https://example.com/a', '2026-02-30', '公开商家资料'], '来源日期'),
    (['美业', 'https://example.com/a', '2026-11-01', 'valid'], '不能声明人工已核实'),
])
async def test_extended_import_rejects_invalid_provenance_or_claimed_human_verification(imports_client, extras, reason):
    client, maker = imports_client
    response = await client.post('/api/v1/merchant-imports/preview', headers=auth(), files={'file': ('invalid.csv', source_csv([[*GOOD, *extras]]), 'text/csv')})
    assert response.status_code == 200, response.text
    batch = response.json()
    assert batch['rows'][0]['status'] == 'error'
    assert reason in batch['rows'][0]['reason']
    assert (await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())).status_code == 400
    assert await count(maker, MerchantPool) == 0


@pytest.mark.asyncio
async def test_placeholder_names_and_addresses_do_not_collide_but_real_phones_still_do(imports_client):
    client, maker = imports_client
    rows = [
        ['店名待核验｜NY美甲招聘联系点', '+12125550123', '街道地址待核验；2026-11-01', 'NY, US', '中文招聘'],
        ['店名待核验｜NY美甲招聘联系点', '+14155550123', '街道地址待核验；2026-11-01', 'NY, US', '中文招聘'],
        ['另一个联系点', '+1 (212) 555-0123 ext 9', '地址待确认', 'NY, US', '中文招聘'],
    ]
    batch = await preview(client, rows)
    assert [r['status'] for r in batch['rows']] == ['pending', 'pending', 'duplicate']
    basis = batch['rows'][2]['match_basis']
    assert basis == {'type': 'phone', 'scope': 'file', 'value': '+12125550123', 'matched_row': 2}
    assert '匹配依据：电话' in batch['rows'][2]['reason']
    assert (await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())).status_code == 200
    next_batch = await preview(client, [[*rows[0][:1], '+13105550123', *rows[0][2:]]])
    assert next_batch['rows'][0]['status'] == 'pending'
    concrete = await preview(client, [GOOD, ['Sample Cafe', '+13055550123', GOOD[2], GOOD[3], 'Maps']])
    assert concrete['rows'][1]['match_basis']['type'] == 'name_address'


@pytest.mark.asyncio
async def test_legacy_json_placeholder_location_does_not_bypass_phone_or_website_duplicate(imports_client):
    client, maker = imports_client
    rows = [
        {'business_name': '店名待核验', 'address': '街道地址待核验', 'country': 'US', 'phone': '+12125550123', 'website': 'https://actual-shop.example.com'},
        {'business_name': '店名待核验', 'address': '街道地址待核验', 'country': 'US', 'phone': '+14155550123'},
        {'business_name': '店名待核验', 'address': '街道地址待核验', 'country': 'US', 'phone': '+13055550123', 'website': 'https://actual-shop.example.com/'},
    ]
    result = await client.post('/api/v1/merchant-pool/import', headers=auth(), json={'records': rows})
    assert result.status_code == 200, result.text
    assert result.json()['counts']['pending'] == 2 and result.json()['counts']['duplicate'] == 1
    assert '网站' in result.json()['items'][2]['isolation_reason']


@pytest.mark.asyncio
async def test_extended_issue_download_preserves_extra_source_columns(imports_client):
    client, _ = imports_client
    content = source_csv([['No Phone', '123', '地址待核验', 'NY, US', '原目录', 'https://example.com/ad', '2026-11-01']], optional_headers=('来源URL', '来源日期'))
    result = await client.post('/api/v1/merchant-imports/preview', headers=auth(), files={'file': ('extended.csv', content, 'text/csv')})
    batch = result.json()
    downloaded = await client.get(f"/api/v1/merchant-imports/{batch['id']}/errors.csv", headers=auth())
    rows = list(csv.reader(io.StringIO(downloaded.content.decode('utf-8-sig'))))
    assert rows[0] == ['原始行号', *HEADERS, '来源URL', '来源日期', '处理结果', '原因']
    assert rows[1][6:8] == ['https://example.com/ad', '2026-11-01']


@pytest.mark.asyncio
@pytest.mark.parametrize('blocked_status', ['invalid_phone', 'not_target', 'closed'])
async def test_quality_blocks_single_and_atomic_bulk_assignment_until_reverified(imports_client, monkeypatch, blocked_status):
    from models.employees import Employees
    from routers import merchant_pool
    client, maker = imports_client
    async with maker() as session:
        session.add(Employees(id=11, user_id='sales-quality-test', name='Sales', role='sales', status='active', supervisor='Manager 10'))
        session.add_all([MerchantPool(id=101, business_name='Pending A', phone='+12125550123', country='US', data_source='test', pool_status='pending', created_by_id=10), MerchantPool(id=102, business_name='Pending B', phone='+14155550123', country='US', data_source='test', pool_status='pending', created_by_id=10)])
        await session.commit()
    status = blocked_status
    async def quality_one(db, kind, entity_id):
        return {'status': status if entity_id == 102 else 'pending'}
    async def quality_many(db, kind, ids):
        return {i: await quality_one(db, kind, i) for i in ids}
    monkeypatch.setattr(merchant_pool, 'quality_for', quality_one)
    monkeypatch.setattr(merchant_pool, 'quality_for_many', quality_many)
    blocked = await client.post('/api/v1/merchant-pool/102/convert-to-lead', headers=auth(), json={})
    assert blocked.status_code == 409, blocked.text
    bulk = await client.post('/api/v1/merchant-pool/bulk-convert-to-lead', headers=auth(), json={'merchant_ids': [101, 102], 'assigned_sales_id': 11})
    assert bulk.status_code == 409, bulk.text
    assert await count(maker, SalesLeads) == 0
    status = 'valid'
    allowed = await client.post('/api/v1/merchant-pool/bulk-convert-to-lead', headers=auth(), json={'merchant_ids': [101, 102], 'assigned_sales_id': 11})
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()['converted_count'] == 2
    assert await count(maker, SalesLeads) == 2


@pytest.mark.asyncio
async def test_json_import_cannot_supply_a_verified_quality_status(imports_client):
    client, maker = imports_client
    response = await client.post('/api/v1/merchant-pool/import', headers=auth(), json={'default_industry': '美业', 'records': [{'business_name': 'Source Only', 'phone': '+12125550123', 'country': 'US', 'prospect_quality': {'status': 'valid', 'verified_by_name': 'Forged'}, 'source_url': 'https://example.com/merchant', 'source_date': '2026-11-01', 'verification_type': 'public_business_profile'}]})
    assert response.status_code == 200, response.text
    async with maker() as session:
        row = (await session.execute(select(MerchantPool))).scalar_one()
        raw = json.loads(row.raw_payload)
        assert row.industry == '美业'
        assert raw['prospect_quality']['status'] == 'pending'
        assert raw['prospect_source']['source_url'] == 'https://example.com/merchant'
        assert raw['prospect_quality'].get('verified_by_name') != 'Forged'


@pytest.mark.asyncio
async def test_authoritative_verification_revision_prevents_undo_even_without_record_edits(imports_client):
    from models.operation_logs import Operation_logs
    from services.prospect_verification import initial_prospect_quality
    client, maker = imports_client
    batch = await preview(client, [GOOD])
    committed = (await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())).json()
    merchant_id = committed['rows'][0]['merchant_id']
    after = initial_prospect_quality()
    after.update(revision=1, status='valid')
    async with maker() as session:
        session.add(Operation_logs(user_id='10', action_type=f'prospect_quality:pool:{merchant_id}', action_detail=json.dumps({'entity_kind': 'pool', 'entity_id': merchant_id, 'after': after})))
        await session.commit()
    undone = await client.post(f"/api/v1/merchant-imports/{batch['id']}/revert", headers=auth())
    assert undone.status_code == 409, undone.text
    assert '核验' in undone.json()['detail']['message']
    assert await count(maker, MerchantPool) == 1
    assert (await client.get(f"/api/v1/merchant-imports/{batch['id']}", headers=auth())).json()['status'] == 'committed'


@pytest.mark.asyncio
async def test_quality_facets_use_visible_industry_scope_before_selected_quality(imports_client):
    from models.operation_logs import Operation_logs
    from services.prospect_verification import initial_prospect_quality
    client, maker = imports_client
    async with maker() as session:
        for row_id, owner, industry in [(200, 10, '美业'), (201, 10, '美业'), (202, 20, '美业'), (203, 10, '餐厅')]:
            session.add(MerchantPool(id=row_id, business_name=f'Contact {row_id}', phone=f'+12125550{row_id}', country='US', state='NY', industry=industry, data_source='sourceA', pool_status='pending', created_by_id=owner))
        for row_id in [201, 202]:
            quality = initial_prospect_quality()
            quality.update(revision=1, status='valid')
            session.add(Operation_logs(user_id='10', action_type=f'prospect_quality:pool:{row_id}', action_detail=json.dumps({'entity_kind': 'pool', 'entity_id': row_id, 'after': quality})))
        await session.commit()
    response = await client.get('/api/v1/merchant-pool?pool_status=pending&industry=美业&source=sourceA&quality_status=valid', headers=auth())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['total'] == 1 and result['items'][0]['id'] == 201
    assert result['items'][0]['prospect_quality']['revision'] == 1
    assert result['quality_facets'] == {'pending': 1, 'valid': 1, 'invalid_phone': 0, 'not_target': 0, 'closed': 0}


@pytest.mark.asyncio
async def test_assigned_lead_inherits_pool_quality_source_and_original_verifier(imports_client):
    from models.employees import Employees
    from schemas.prospect_verification import ProspectVerificationUpdate
    from services.prospect_verification import quality_for, save_verification, verification_view
    client, maker = imports_client
    async with maker() as session:
        session.add_all([
            Employees(id=10, user_id='manager-quality', name='Manager 10', role='sales_manager', status='active'),
            Employees(id=11, user_id='assigned-quality-sales', name='Sales', role='sales', status='active', supervisor='Manager 10'),
            Employees(id=20, user_id='original-quality-admin', name='Original Verifier', role='admin', status='active'),
        ])
        await session.commit()
    content = source_csv([[*GOOD, '美业', 'https://example.com/original-profile', '2026-11-01', '公开商家资料']])
    batch = (await client.post('/api/v1/merchant-imports/preview', headers=auth(), files={'file': ('verified-source.csv', content, 'text/csv')})).json()
    receipt = (await client.post(f"/api/v1/merchant-imports/{batch['id']}/confirm", headers=auth())).json()
    merchant_id = receipt['rows'][0]['merchant_id']
    async with maker() as session:
        original = await save_verification(session, 'pool', merchant_id, UserResponse(id='20', email='verifier@example.com', role='admin', name='Original Verifier'), ProspectVerificationUpdate(expected_revision=0, status='valid', method='call', notes='Reached store and confirmed business details', corrected_fields={'chinese_service': 'yes'}))
        await session.commit()
    assigned = await client.post('/api/v1/merchant-pool/bulk-convert-to-lead', headers=auth(), json={'merchant_ids': [merchant_id], 'assigned_sales_id': 11})
    assert assigned.status_code == 200, assigned.text
    lead_id = assigned.json()['lead_ids'][0]
    async with maker() as session:
        quality = await quality_for(session, 'lead', lead_id)
        assert quality['status'] == 'valid' and quality['revision'] == 1
        assert quality['verified_by_id'] == original['verified_by_id'] == 20
        assert quality['verified_by_name'] == original['verified_by_name'] == 'Original Verifier'
        assert quality['verified_at'] == original['verified_at']
        assert quality['origin'] == {'entity_kind': 'pool', 'entity_id': merchant_id, 'revision': original['revision']}
        view = await verification_view(session, 'lead', lead_id, UserResponse(id='10', email='10@example.com', role='sales_manager', name='Manager 10'))
        assert view['prospect_source']['source_url'] == 'https://example.com/original-profile'
        assert view['prospect_source']['source_date'] == '2026-11-01'
        assert view['prospect_source']['verification_type'] == 'public_business_profile'
        assert (await quality_for(session, 'pool', merchant_id)) == original
