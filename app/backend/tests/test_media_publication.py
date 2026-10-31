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


# Action-history DTOs expose the frozen outbound configuration, never current
# task fields, private assets or arbitrary nested JSON.
def history_action(payload, *, kind="post_publish", created_at=None):
    from datetime import datetime, timezone
    from models.google_business import GoogleBusinessAction
    at = created_at or datetime(2026, 10, 31, tzinfo=timezone.utc)
    return GoogleBusinessAction(id=1, binding_id=1, customer_id=10, kind=kind, request_id="history-test",
        actor_name="Operator", status="succeeded", payload=payload, created_at=at, updated_at=at,
        message="Confirmed")


def test_history_offer_projects_frozen_public_fields_and_preserves_local_wall_time(monkeypatch):
    from datetime import datetime, timezone
    from services import google_business as google
    monkeypatch.setattr(google, "now", lambda: datetime(2026, 10, 31, tzinfo=timezone.utc))
    payload = {"topicType": "OFFER", "summary": "Approved offer", "event": {"title": "Open house",
        "schedule": {"startDate": {"year": 2026, "month": 12, "day": 1},
            "startTime": {"hours": 9, "minutes": 0, "seconds": 0, "nanos": 0},
            "endDate": {"year": 2026, "month": 12, "day": 1},
            "endTime": {"hours": 10, "minutes": 0}}, "credential": "not-public"},
        "offer": {"couponCode": "VISIT10", "redeemOnlineUrl": "https://offers.example.com/?offer=10",
            "termsConditions": "One per person", "token": "not-public"},
        "media": [{"sourceUrl": "https://private.example.com/?signed=secret"}], "credential": "not-public"}
    frozen = copy.deepcopy(payload)
    result = google.action_data(history_action(payload), None)
    expected = {"topicType": "OFFER", "event": copy.deepcopy(payload["event"]), "offer": copy.deepcopy(payload["offer"])}
    expected["event"].pop("credential"); expected["offer"].pop("token")
    assert result["publication_payload"] == expected
    assert "timezone" not in result["publication_payload"] and "start_at" not in result["publication_payload"]["event"]
    result["publication_payload"]["event"]["schedule"]["startTime"]["hours"] = 1
    assert payload == frozen


def test_history_standard_has_only_configuration_whitelist_and_full_cta(monkeypatch):
    from datetime import datetime, timezone
    from services import google_business as google
    monkeypatch.setattr(google, "now", lambda: datetime(2026, 10, 31, tzinfo=timezone.utc))
    cta = {"actionType": "BOOK", "url": "https://booking.example.com/?service=1"}
    row = google.action_data(history_action({"topicType": "STANDARD", "summary": "Frozen text",
        "callToAction": {**cta, "private": {"secret": "never"}}, "media": []}), None)
    assert row["publication_payload"] == {"topicType": "STANDARD", "callToAction": cta}
    assert row["content"] == "Frozen text"


def test_history_expired_payload_is_not_returned_even_before_database_cleanup(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from services import google_business as google
    at = datetime(2026, 10, 31, tzinfo=timezone.utc)
    monkeypatch.setattr(google, "now", lambda: at)
    row = google.action_data(history_action({"topicType": "STANDARD", "summary": "Expired"},
        created_at=at - timedelta(days=30, microseconds=1)), None)
    assert row["publication_payload"] is None and row["content"] is None


def test_history_nonpost_actions_do_not_expose_configuration(monkeypatch):
    from datetime import datetime, timezone
    from services import google_business as google
    monkeypatch.setattr(google, "now", lambda: datetime(2026, 10, 31, tzinfo=timezone.utc))
    for kind in ("review_reply", "grant_updated", "binding_disconnected"):
        row = google.action_data(history_action({"topicType": "OFFER", "offer": {"couponCode": "secret"}}, kind=kind), None)
        assert row["publication_payload"] is None


def test_history_null_or_malformed_payload_is_safe_and_never_copies_nested_json(monkeypatch):
    from datetime import datetime, timezone
    from services import google_business as google
    monkeypatch.setattr(google, "now", lambda: datetime(2026, 10, 31, tzinfo=timezone.utc))
    for payload in (None, [], {}, {"topicType": None}, {"topicType": ["OFFER"]}):
        assert google.action_data(history_action(payload), None)["publication_payload"] is None
    payload = {"topicType": "EVENT", "event": {"title": {"secret": "never"}, "schedule": {
        "startDate": {"year": True, "month": 99, "day": {"secret": "never"}},
        "startTime": {"hours": -1, "minutes": "30", "nanos": 1000000000}}},
        "callToAction": {"actionType": {"secret": "never"}, "url": ["never"]}}
    assert google.action_data(history_action(payload), None)["publication_payload"] == {
        "topicType": "EVENT", "event": {"schedule": {"startDate": {}, "startTime": {}}}, "callToAction": {}}
