import pytest

from backend.tests.test_sales_lead_isolation import _auth_headers, sales_app_client


@pytest.mark.asyncio
async def test_merchant_analysis_is_source_bound_and_sales_is_blocked(sales_app_client):
    manager = _auth_headers("sales_manager", 10, "Manager A")
    sales = _auth_headers("sales", 11, "Sales A")

    imported = await sales_app_client.post(
        "/api/v1/merchant-pool/import",
        headers=manager,
        json={
            "data_source": "api",
            "records": [
                {
                    "business_name": "Evidence Cafe",
                    "phone": "555-9876",
                    "industry": "餐厅",
                    "city": "Los Angeles",
                    "state": "CA",
                    "country": "US",
                    "website": "https://evidence.example",
                    "google_business_url": "https://maps.google.com/evidence",
                    "google_rating": 4.1,
                    "google_review_count": 22,
                    "recent_negative_reviews": "已采集：两条评论提到等待时间长",
                }
            ],
        },
    )
    assert imported.status_code == 200
    merchant_id = imported.json()["items"][0]["id"]

    generated = await sales_app_client.post(
        f"/api/v1/merchant-pool/{merchant_id}/analysis/generate",
        headers=manager,
    )
    assert generated.status_code == 200
    payload = generated.json()
    cards = {item["title"]: item for item in payload["analysis"]["cards"]}

    assert cards["Google 商家情况"]["kind"] == "fact"
    assert cards["Google 商家情况"]["sources"][0]["label"] == "Google 商家链接"
    assert cards["Yelp 情况"]["kind"] == "insufficient"
    assert cards["Yelp 情况"]["content"].startswith("信息不足：")
    assert "成交可能性评分" in cards
    for card in cards.values():
        assert card["sources"]
        for source in card["sources"]:
            assert "label" in source
            assert "updated_at" in source

    latest = await sales_app_client.get(
        f"/api/v1/merchant-pool/{merchant_id}/analysis",
        headers=manager,
    )
    blocked = await sales_app_client.get(
        f"/api/v1/merchant-pool/{merchant_id}/analysis",
        headers=sales,
    )
    assert latest.status_code == 200
    assert latest.json()["id"] == payload["id"]
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_merchant_enrichment_keeps_raw_import_evidence_and_never_overwrites(sales_app_client):
    manager = _auth_headers("sales_manager", 10, "Manager A")
    imported = await sales_app_client.post(
        "/api/v1/merchant-pool/import",
        headers=manager,
        json={
            "data_source": "bulk",
            "records": [{
                "business_name": "Raw Evidence Spa",
                "phone": "555-1122",
                "industry": "美业",
                "Google Rating": 4.7,
                "Yelp URL": "https://yelp.example/raw-evidence",
            }],
        },
    )
    assert imported.status_code == 200
    merchant_id = imported.json()["items"][0]["id"]

    suggested = await sales_app_client.post(
        "/api/v1/merchant-pool/enrichment/suggest",
        headers=manager,
        json={"merchant_ids": [merchant_id]},
    )
    assert suggested.status_code == 200
    suggestions = suggested.json()["items"][0]["suggestions"]
    assert {item["field"] for item in suggestions} == {"google_rating", "yelp_url"}
    assert all(item["source_label"] == "原始导入资料" for item in suggestions)

    applied = await sales_app_client.post(
        "/api/v1/merchant-pool/enrichment/apply",
        headers=manager,
        json={"items": [{"merchant_id": merchant_id, "suggestions": suggestions}]},
    )
    assert applied.status_code == 200
    assert applied.json()["applied_count"] == 2

    merchants = await sales_app_client.get(
        "/api/v1/merchant-pool",
        headers=manager,
        params={"search": "Raw Evidence Spa"},
    )
    assert merchants.status_code == 200
    merchant = merchants.json()["items"][0]
    assert merchant["google_rating"] == 4.7
    assert merchant["yelp_url"] == "https://yelp.example/raw-evidence"

    overwrite = await sales_app_client.post(
        "/api/v1/merchant-pool/enrichment/apply",
        headers=manager,
        json={"items": [{"merchant_id": merchant_id, "suggestions": [{
            "field": "google_rating",
            "value": 1.0,
            "source_label": "伪造来源",
            "confidence": 1.0,
        }]}]},
    )
    assert overwrite.status_code == 200
    assert overwrite.json()["skipped_count"] == 1
