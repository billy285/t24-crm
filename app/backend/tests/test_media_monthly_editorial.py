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


def test_unified_mix_exact_rounding_and_interleaving_preserves_slots():
    from collections import Counter
    for total in range(1, 32):
        for mix in ({"featured":50,"discovery":30,"business":20}, {"featured":0,"discovery":0,"business":100}, {"featured":34,"discovery":33,"business":33}):
            counts = editorial.topic_counts(total, mix)
            sequence = editorial.topic_sequence(total, mix)
            assert sum(counts.values()) == len(sequence) == total
            assert dict(Counter(sequence)) == {k:v for k,v in counts.items() if v}
            assert sequence == editorial.topic_sequence(total, mix)
    assert editorial.topic_counts(12, {"featured":50,"discovery":30,"business":20}) == {"featured":6,"discovery":4,"business":2}
    source = snapshot(); source['rules']['_automation_plan'] = {'content_mix':{'featured':50,'discovery':30,'business':20},'tone':'professional'}
    original = copy.deepcopy(source)
    result = editorial.directions(source)
    assert source == original and [r['slot_id'] for r in result] == [s['slot_id'] for s in source['slots']]
    assert Counter(r['topic'] for r in result) == {'featured':6,'discovery':4,'business':2}
    assert all(r['tone'] == 'professional' for r in result)
    payload = monthly._ai_payload(source)
    assert Counter(r['topic'] for r in payload['editorial_plan']) == {'featured':6,'discovery':4,'business':2}
    assert '$99' not in str(payload) and 'PRIVATE' not in str(payload)
