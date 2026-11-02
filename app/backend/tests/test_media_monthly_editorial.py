"""Editorial checks use synthetic public text and never call an AI service."""
import copy
from services import media_monthly_editorial as editorial
from services import media_monthly as monthly


def snapshot(platform="instagram"):
    return {"platform": platform, "public_facts": {"public_name": "Example", "location": "Example City", "highlights": ["Confirmed products"]},
            "menu_items": [{"id": 1, "name": "Example bowl", "category": "Bowls", "selling_points": "Confirmed dish", "price": "$99"}],
            "rules": {"language": "en", "include_prices": False, "forbidden_claims": []},
            "slots": [{"slot_id": str(index), "menu_item_ids": [1], "proposed_publish_at": "NOT_SENT"} for index in range(12)],
            "images": [{"file_path": "PRIVATE_PATH", "notes": "PRIVATE_NOTES"}]}


def test_direction_rotates_same_product_without_dates_facts_or_source_mutation():
    source = snapshot(); original = copy.deepcopy(source)
    result = editorial.directions(source)
    assert source == original and len(result) == 12
    assert [r["slot_id"] for r in result] == [str(i) for i in range(12)]
    assert len({r["angle"] for r in result}) > 2
    assert sum(r["cta"] == "question" for r in result) == 2
    assert all(set(r) == {"slot_id", "angle", "direction", "cta"} for r in result)


def test_provider_payload_keeps_only_confirmed_public_text_and_editorial_metadata():
    payload = monthly._ai_payload(snapshot())
    encoded = str(payload)
    assert payload["platform"] == "instagram"
    assert len(payload["editorial_plan"]) == 12
    assert not any(secret in encoded for secret in ("NOT_SENT", "PRIVATE_PATH", "PRIVATE_NOTES", "$99"))
    assert "Instagram" in editorial.instructions("instagram")
    assert "Facebook" in editorial.instructions("facebook")
    assert "Google" in editorial.instructions("google_business")


def test_near_duplicates_and_internal_language_are_hints_not_approval_or_mutation():
    sentence = "The official menu lists Example bowl under Bowls. This is confirmed menu information for Example City."
    items = [{"id": 4, "content": sentence}, {"id": 5, "content": sentence + " #Example"}]
    original = copy.deepcopy(items)
    result = editorial.review(items)
    assert items == original
    assert result["needs_review"] and result["duplicate_groups"] == 1
    assert result["process_language_items"] == 2
    assert set(result["item_warnings"]) == {"4", "5"}
    assert not any(key in result for key in ("approved", "adoptable", "scheduled", "publication_confirmed"))


def test_distinct_customer_facing_copy_and_empty_legacy_run_are_supported():
    items = [{"id": 1, "content": "Meet Example bowl. A bowl or a roll—which gets your vote?"},
             {"id": 2, "content": "Put a burrito in the rotation. Save a menu idea for your next visit."}]
    assert not editorial.review(items)["needs_review"]
    assert editorial.review([])["item_warnings"] == {}
