"""Focused conversion tests; no provider, HTTP or file credentials are used."""
import copy

import pytest
from fastapi import HTTPException

from services import media_operations as media


@pytest.mark.parametrize("action", ["BOOK", "ORDER", "SHOP", "LEARN_MORE", "SIGN_UP", "CALL"])
def test_each_supported_cta_has_exact_provider_shape_and_stable_normalization(action):
    cta = {"action_type": action}
    expected = {"actionType": action}
    if action != "CALL":
        cta["url"] = "https://booking.example.com/visit?service=spa&time=09%3A00"
        expected["url"] = cta["url"]
    original = {"topic_type": "STANDARD", "call_to_action": cta}
    frozen = copy.deepcopy(original)
    normalized = media.normalize_publication(original, "google_business", "America/New_York")
    assert media.normalize_publication(normalized, "google_business", "America/New_York") == normalized
    assert media.publication_payload(normalized, "America/New_York") == {
        "topicType": "STANDARD", "callToAction": expected}
    assert original == frozen


@pytest.mark.parametrize("zone,instant,day,hour", [
    ("America/Los_Angeles", "2028-03-01T00:00:00Z", (2028, 2, 29), 16),
    ("Asia/Shanghai", "2028-02-29T18:00:00Z", (2028, 3, 1), 2),
])
def test_utc_instants_convert_to_whole_local_dates_without_host_timezone(zone, instant, day, hour):
    from datetime import datetime, timedelta
    start = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    value = {"topic_type": "EVENT", "event": {"title": "Confirmed event", "start_at": instant,
        "end_at": (start + timedelta(hours=1)).isoformat()}}
    payload = media.publication_payload(value, zone)
    schedule = payload["event"]["schedule"]
    assert schedule["startDate"] == dict(zip(("year", "month", "day"), day))
    assert schedule["startTime"] == {"hours": hour, "minutes": 0, "seconds": 0, "nanos": 0}
    assert "scheduledTime" not in payload and "recurrence" not in payload


@pytest.mark.parametrize("key", ["scheduledTime", "recurrence", "alertType", "media"])
def test_provider_only_fields_cannot_enter_crm_publication_spec(key):
    with pytest.raises(HTTPException) as exc:
        media.normalize_publication({"topic_type": "STANDARD", key: {}}, "google_business", "UTC")
    assert exc.value.status_code == 422


def test_default_result_is_not_shared_mutable_state():
    result = media.normalize_publication(None, "google_business", "UTC")
    result["topic_type"] = "OFFER"
    assert media.normalize_publication(None, "google_business", "UTC") == {"topic_type": "STANDARD"}
    assert media.publication_payload(None, "UTC") == {"topicType": "STANDARD"}
