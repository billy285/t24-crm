import pytest

from backend.tests.test_sales_dossiers import auth, dossier_api
from backend.tests.test_sales_closing_queue import historical_merchant


LEADS = "/api/v1/sales-leads"


@pytest.mark.asyncio
async def test_personal_stars_and_team_priority_have_separate_visibility(dossier_api):
    client, sessions = dossier_api
    async with sessions.begin() as db:
        db.add(historical_merchant(871, status="interested", team_manager_id=10))
        db.add(historical_merchant(872, status="interested", assigned=12))

    path = f"{LEADS}/871/markers"
    for _ in range(2):
        response = await client.put(path, json={"starred": True}, headers=auth(11))
        assert response.status_code == 200, response.text
        assert response.json() == {"starred": True, "priority": False}
    assert (await client.put(path, json={"priority": True}, headers=auth(11))).status_code == 403
    assert (await client.put(path, json={"starred": True}, headers=auth(12))).status_code == 404
    assert (await client.put(f"{LEADS}/872/markers", json={"priority": True}, headers=auth(10))).status_code == 404
    response = await client.put(path, json={"priority": True}, headers=auth(10))
    assert response.json() == {"starred": False, "priority": True}

    for identity, found in [(11, [871]), (10, []), (1, [])]:
        response = await client.get(LEADS, params={"starred": True}, headers=auth(identity))
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == found
    for identity in (11, 10, 1):
        response = await client.get(LEADS, params={"priority": True}, headers=auth(identity))
        assert [item["id"] for item in response.json()["items"]] == [871]
    response = await client.get(f"{LEADS}/closing-queue", params={"priority": True}, headers=auth(1))
    assert [item["lead_id"] for item in response.json()["items"]] == [871]
    assert response.json()["items"][0]["starred"] is False

    response = await client.put(path, json={"starred": False}, headers=auth(11))
    assert response.json() == {"starred": False, "priority": True}
    response = await client.put(path, json={"priority": False}, headers=auth(10))
    assert response.json() == {"starred": False, "priority": False}
