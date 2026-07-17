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
