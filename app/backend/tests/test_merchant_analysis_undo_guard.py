import importlib
import pytest
from sqlalchemy import delete, func, select
from backend.main import app
from backend.tests.test_sales_lead_isolation import _auth_headers, sales_app_client
from models.merchant_pool import MerchantPool
from models.merchant_ai_analyses import MerchantAiAnalyses
from core.database import get_db

@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deleted", "edited"])
async def test_analysis_rechecks_existence_and_evidence_after_ai_wait(sales_app_client, monkeypatch, change):
    manager=_auth_headers("sales_manager",10,"Manager A")
    imported=await sales_app_client.post("/api/v1/merchant-pool/import",headers=manager,json={"records":[{"business_name":"Analysis race","phone":"+12125550131","country":"US"}]})
    merchant_id=imported.json()["items"][0]["id"]
    module=importlib.import_module("routers.merchant_ai_analysis")
    async def delayed_ai(merchant,evidence,db):
        if change == "deleted":
            await db.execute(delete(MerchantPool).where(MerchantPool.id==merchant_id))
        else:
            merchant.business_name="New name after AI snapshot"
        await db.commit()
        return [],False,None,"",None
    monkeypatch.setattr(module,"_generate_ai_cards",delayed_ai)
    result=await sales_app_client.post(f"/api/v1/merchant-pool/{merchant_id}/analysis/generate",headers=manager)
    assert result.status_code == (404 if change == "deleted" else 409)
    async for db in app.dependency_overrides[get_db]():
        assert await db.scalar(select(func.count(MerchantAiAnalyses.id))) == 0
