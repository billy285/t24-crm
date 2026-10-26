"""Synthetic evidence permissions, bounds and audit tests; no business posting."""
import hashlib
from datetime import datetime, timezone
import asyncio
import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.customer_access_grants import CustomerAccessGrant
from models.customers import Customers
from models.finance_entry_attachments import FinanceEntryAttachment
from models.finance_entry_drafts import FinanceEntryDraft, FinanceEntryDraftAudit
from services.finance_entry_attachments import MAX_FILE_BYTES
from fastapi import HTTPException, UploadFile
from schemas.auth import UserResponse

PDF = b"%PDF-1.4\nsynthetic evidence only\n%%EOF"


def headers(role="finance", ident=501):
    return {"Authorization": "Bearer " + create_access_token({
        "emp_id": ident, "role": role, "name": "Synthetic clerk", "email": f"{ident}@example.test"})}


@pytest_asyncio.fixture
async def evidence_api():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE TABLE IF NOT EXISTS app_settings (config_key TEXT PRIMARY KEY, value_json TEXT)"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        db.add(Customers(id=1, business_name="Synthetic authorized", contact_name="A", phone="111"))
        db.add(CustomerAccessGrant(customer_id=1, employee_id=501, access_level="read_only",
            scopes={"basic": "read_only"}, finance_access="receipts", invitation_status="active",
            invitation_source="owner_invitation"))
        for ident, actor, status in [(1, 501, "draft"), (2, 502, "draft"), (3, 501, "submitted")]:
            db.add(FinanceEntryDraft(id=ident, customer_id=1, customer_name="Synthetic authorized",
                kind="manual_receipt", created_by_id=actor, created_by_name="Synthetic clerk",
                client_request_id=f"synthetic-{ident}", creation_fingerprint="0" * 64, payload={},
                status=status, revision=1, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
        await db.commit()
        async def override():
            yield db
        app.dependency_overrides[get_db] = override
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, db
        app.dependency_overrides.clear()
    await engine.dispose()


async def upload(client, draft=1, revision=1, data=PDF, auth=None, filename="receipt.pdf"):
    return await client.post(f"/api/v1/finance-entry-drafts/{draft}/attachments", headers=auth or headers(),
        data={"expected_revision": revision}, files={"file": (filename, data, "application/octet-stream")})


@pytest.mark.asyncio
async def test_private_upload_download_revision_audit_and_duplicate(evidence_api):
    client, db = evidence_api
    result = await upload(client, filename="../../unsafe.html")
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["draft_revision"] == 2
    item = value["item"]
    assert item["filename"] == "unsafe.pdf" and item["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert "content" not in item
    path = f"/api/v1/finance-entry-drafts/1/attachments/{item['id']}"
    for auth in [headers(), headers("super_admin", 1)]:
        res = await client.get(path, headers=auth)
        assert res.content == PDF and res.status_code == 200
        assert res.headers["content-type"] == "application/pdf"
        assert "attachment;" in res.headers["content-disposition"]
        assert "no-store" in res.headers["cache-control"] and res.headers["x-content-type-options"] == "nosniff"
    duplicate = await upload(client, revision=2)
    assert duplicate.status_code == 200 and duplicate.json()["item"]["id"] == item["id"]
    assert duplicate.json()["draft_revision"] == 2
    assert len((await db.scalars(select(FinanceEntryDraftAudit))).all()) == 1
    assert len((await db.scalars(select(FinanceEntryAttachment))).all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("role,actor", [("finance", 502), ("sales", 501), ("admin", 501), ("ops", 501)])
async def test_other_staff_never_read_or_upload_evidence(evidence_api, role, actor):
    client, _ = evidence_api
    assert (await upload(client)).status_code == 200
    auth = headers(role, actor)
    for path in ["/api/v1/finance-entry-drafts/1/attachments", "/api/v1/finance-entry-drafts/1/attachments/1"]:
        assert (await client.get(path, headers=auth)).status_code in (403, 404)
    assert (await upload(client, revision=2, auth=auth)).status_code in (403, 404)


@pytest.mark.asyncio
async def test_revoked_customer_grant_immediately_hides_evidence(evidence_api):
    client, db = evidence_api
    assert (await upload(client)).status_code == 200
    grant = (await db.scalars(select(CustomerAccessGrant))).one()
    grant.invitation_status = "revoked"
    await db.commit()
    assert (await client.get("/api/v1/finance-entry-drafts/1/attachments", headers=headers())).status_code in (403, 404)
    assert (await client.get("/api/v1/finance-entry-drafts/1/attachments/1", headers=headers())).status_code in (403, 404)
    assert (await upload(client, revision=2)).status_code in (403, 404)
    assert len((await db.scalars(select(FinanceEntryAttachment))).all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [b"<script>alert(1)</script>", b"", b"%PDF-" + b"x" * MAX_FILE_BYTES])
async def test_evidence_rejects_unsupported_empty_or_oversized_data(evidence_api, data):
    client, db = evidence_api
    assert (await upload(client, data=data)).status_code == 422
    assert not (await db.scalars(select(FinanceEntryAttachment))).all()
    assert (await db.get(FinanceEntryDraft, 1)).revision == 1


@pytest.mark.asyncio
async def test_submitted_and_stale_drafts_are_not_changed(evidence_api):
    client, db = evidence_api
    assert (await upload(client, draft=3)).status_code in (403, 409)
    assert (await upload(client)).status_code == 200
    assert (await upload(client, revision=1, data=PDF+b"other")).status_code == 409
    assert (await upload(client, revision=2, auth=headers("super_admin", 1))).status_code == 409
    assert (await db.get(FinanceEntryDraft, 1)).revision == 2


@pytest.mark.asyncio
async def test_soft_removal_keeps_bytes_and_audit(evidence_api):
    client, db = evidence_api
    assert (await upload(client)).status_code == 200
    res = await client.delete("/api/v1/finance-entry-drafts/1/attachments/1", params={"expected_revision": 2}, headers=headers())
    assert res.status_code == 200 and res.json()["draft_revision"] == 3
    assert (await client.get("/api/v1/finance-entry-drafts/1/attachments/1", headers=headers())).status_code == 404
    res = await client.get("/api/v1/finance-entry-drafts/1/attachments", headers=headers())
    assert res.json()["items"] == []
    row = await db.get(FinanceEntryAttachment, 1)
    assert row.content == PDF and row.removed_at is not None and row.removed_by_id == 501
    assert len((await db.scalars(select(FinanceEntryDraftAudit))).all()) == 2


@pytest.mark.asyncio
async def test_unauthenticated_file_routes_are_closed(evidence_api):
    client, _ = evidence_api
    for path in ["/api/v1/finance-entry-drafts/1/attachments", "/api/v1/finance-entry-drafts/1/attachments/1"]:
        assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_file_sqlite_attachment_and_submission_claim_one_revision(tmp_path):
    from services.finance_entry_attachments import add_attachment
    from services.finance_entry_drafts import transition_draft
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'isolated-evidence-race.db'}", connect_args={"timeout": 10})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user = UserResponse(id="501", role="finance", name="Synthetic clerk", email="501@example.test")
    async with maker() as db:
        db.add(Customers(id=1, business_name="Synthetic authorized", contact_name="A", phone="111"))
        db.add(CustomerAccessGrant(customer_id=1, employee_id=501, access_level="read_only", scopes={"basic": "read_only"},
            finance_access="receipts", invitation_status="active", invitation_source="owner_invitation"))
        db.add(FinanceEntryDraft(id=1, kind="manual_receipt", customer_id=1, customer_name="Synthetic authorized",
            created_by_id=501, created_by_name="Synthetic clerk", client_request_id="synthetic-race-create",
            creation_fingerprint="0"*64, payload={"currency":"USD", "income_type":"management_fee", "product_name":"Synthetic service",
                "amount_due":100, "amount_paid":100, "payment_date":"2026-10-01T00:00:00Z", "payment_method":"check", "evidence_reference":"合成回单"},
            status="draft", revision=1, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
        await db.commit()
    async def run(action):
        async with maker() as db:
            try:
                if action == "upload":
                    await add_attachment(db, user, 1, 1, UploadFile(filename="synthetic.pdf", file=io.BytesIO(PDF)))
                else:
                    await transition_draft(db, user, 1, expected_revision=1, request_id="synthetic-race-submit", action="submit")
                return action
            except HTTPException as error:
                assert error.status_code == 409
                await db.rollback()
                return "conflict"
    try:
        outcomes = await asyncio.gather(run("upload"), run("submit"))
        assert outcomes.count("conflict") == 1
        async with maker() as db:
            draft = await db.get(FinanceEntryDraft, 1)
            assert draft.revision == 2
            count = len((await db.scalars(select(FinanceEntryAttachment))).all())
            assert (draft.status == "submitted" and count == 0) or (draft.status == "draft" and count == 1)
            assert len((await db.scalars(select(FinanceEntryDraftAudit))).all()) == 1
    finally:
        await engine.dispose()
