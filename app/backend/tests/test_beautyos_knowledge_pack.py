"""Sales-content acceptance: scope, usable answers and unapproved promises."""

import copy
import re
from collections import Counter
from difflib import SequenceMatcher

import pytest

import services.beautyos_knowledge_pack as pack


def by_key(suffix):
    return next(card for card in pack.BEAUTYOS_KNOWLEDGE_PACK if card["key"] == "beautyos-" + suffix)


def public_copy(card):
    return card["phone_answer"] + "\n" + card["standard_answer"]


def test_sixty_distinct_guides_cover_all_stages_and_twenty_priority_tasks():
    cards = pack.BEAUTYOS_KNOWLEDGE_PACK
    assert len(cards) == 60
    assert sum(card["high_frequency"] for card in cards) == 20
    assert Counter(card["category"] for card in cards) == {
        "首拨核验": 8, "需求诊断": 8, "功能与场景": 16, "异议处理": 10,
        "演示邀约": 5, "试用与回访": 5, "成交与交接": 4, "边界与售后": 4,
    }
    assert len({card["key"] for card in cards}) == 60
    assert len({card["title"] for card in cards}) == 60
    assert [card["sort_order"] for card in cards] == list(range(10, 601, 10))
    assert all(re.fullmatch(r"beautyos-[a-z][a-z0-9-]+", card["key"]) for card in cards)
    assert {store for card in cards for store in card["store_types"]} == set(pack.STORE_TYPES)


@pytest.mark.parametrize("card", pack.BEAUTYOS_KNOWLEDGE_PACK, ids=lambda card: card["key"])
def test_each_card_is_a_standalone_customer_answer_and_a_specific_sales_task(card):
    assert card["product_scope"] == "beautyos"
    assert card["category"] in pack.STAGES
    assert card["availability"] in pack.AVAILABILITIES
    assert isinstance(card["high_frequency"], bool)
    for field in ("title", "customer_question", "phone_answer", "standard_answer",
                  "followup_question", "next_action", "internal_notes", "escalation_rule"):
        assert isinstance(card[field], str) and card[field].strip(), field
    # About 15–30 seconds at ordinary Chinese phone-speaking speed, with enough
    # context to copy the short answer on its own rather than truncating a page.
    assert 45 <= len(card["phone_answer"]) <= 120
    assert len(card["standard_answer"]) > len(card["phone_answer"])
    assert card["phone_answer"] != card["standard_answer"]
    assert not any(word in card["phone_answer"] for word in ("见上文", "详见完整版", "点击展开", "内部备注"))
    assert not any(word in card["standard_answer"] for word in (
        "销售应", "销售负责", "销售只能", "销售不", "销售演示", "演示应", "测试只能", "接手人应",
    ))
    assert 2 <= len(card["demo_steps"]) <= 6
    assert 2 <= len(card["action_steps"]) <= 12
    assert all(isinstance(item, str) and len(item.strip()) >= 8 for item in card["demo_steps"] + card["action_steps"])
    assert card["tags"] and len(card["tags"]) <= 12
    assert card["store_types"] and set(card["store_types"]) <= set(pack.STORE_TYPES)
    assert pack.POLICY_REVIEW_NOTE not in public_copy(card)


def test_different_titles_are_not_repeated_template_answers():
    cards = pack.BEAUTYOS_KNOWLEDGE_PACK
    assert len({card["phone_answer"] for card in cards}) == 60
    assert len({card["standard_answer"] for card in cards}) == 60
    assert len({tuple(card["demo_steps"]) for card in cards}) == 60
    # Catch a later title-only expansion or near-duplicate copy, while allowing
    # consistent terms for booking, consent and provider boundaries.
    for index, first in enumerate(cards):
        for second in cards[index + 1:]:
            similarity = SequenceMatcher(None, first["standard_answer"], second["standard_answer"]).ratio()
            assert similarity < 0.88, (first["key"], second["key"], similarity)


def test_unverified_prices_trial_duration_and_commercial_promises_are_not_in_public_copy():
    for card in pack.BEAUTYOS_KNOWLEDGE_PACK:
        customer_text = public_copy(card)
        assert not re.search(r"(?:\$\s*\d|\d+\s*(?:美元|美金|天免费|天试用)|(?:30|60)\s*天)", customer_text)
        assert not any(phrase in customer_text for phrase in (
            "保证排名第一", "保证每天新增", "保证增加营业额", "保证收益", "零停机迁移",
            "无需绑卡", "不会自动续费", "永久免费", "百分之百送达", "所有设备都支持",
        ))
        assert not any(token in customer_text for token in (
            "preview-only", "provider-gated", "CAPABILITY_RELEASE_STATUS", "65e9b716", "Stripe Price ID",
        ))


@pytest.mark.parametrize("suffix", ("objection-price", "objection-trial-trust", "trial-current-terms", "trial-end-renew-cancel"))
def test_commercial_policy_conflict_stays_internal_until_rules_are_confirmed(suffix):
    card = by_key(suffix)
    assert card["availability"] == "pending_confirmation"
    assert "当前" in public_copy(card) and "核" in public_copy(card)
    assert card["internal_notes"] == pack.POLICY_REVIEW_NOTE
    assert "免费使用30天，免费使用期间是不收取任何费用，没有合同限制，不满意可以随时取消" in card["internal_notes"]
    assert "发布前" in card["internal_notes"] and "60天" in card["internal_notes"]
    assert "30天" not in public_copy(card) and "60天" not in public_copy(card)


@pytest.mark.parametrize("suffix", ("feature-checkout-payment", "feature-sms", "feature-email-automation", "feature-google", "feature-ai"))
def test_external_channels_payments_and_ai_never_look_unconditionally_open(suffix):
    card = by_key(suffix)
    assert card["availability"] == "requires_setup"
    assert any(term in public_copy(card) for term in ("配置", "开通", "授权", "就绪"))
    assert any(term in card["demo_steps"][0] + card["demo_steps"][1] for term in ("核对", "检查", "状态", "实际"))
    assert "不" in card["internal_notes"]


def test_preview_features_medical_claims_and_unknown_migration_are_not_sellable_defaults():
    previews = by_key("objection-preview-features")
    assert previews["availability"] == "pending_confirmation"
    assert all(term in previews["internal_notes"] for term in ("loyalty", "giftCards", "social", "preview-only"))
    assert "不能" in public_copy(previews)
    medical = by_key("diagnosis-medspa")
    assert medical["availability"] == "pending_confirmation"
    assert "医美经营" in medical["store_types"]
    assert "病历" in medical["internal_notes"] and "不作医疗合规" in medical["internal_notes"]
    for suffix in ("handoff-data-migration", "support-custom-hardware", "objection-data-security"):
        assert by_key(suffix)["availability"] == "pending_confirmation"


def test_first_call_outcomes_distinguish_contact_role_store_validity_and_refusal():
    assert "不把接通等同有效门店" in by_key("opening-store-check")["next_action"]
    assert "保持待核验" in by_key("opening-recruitment-contact")["next_action"]
    assert "未接通也不能标空号" in by_key("opening-not-a-store")["internal_notes"]
    stop = by_key("opening-stop-contact")
    assert "停止" in stop["phone_answer"]
    assert "不再追问" in stop["followup_question"]
    assert "暂停该线索" in stop["escalation_rule"]
    assert "不能只写" in stop["internal_notes"]


def test_payment_demo_avoids_real_charges_and_post_sale_results_require_verification():
    assert "不发起真实交易" in "".join(by_key("feature-checkout-payment")["demo_steps"])
    assert "不在真实客户权益上" in by_key("demo-package-redemption")["internal_notes"]
    refund = by_key("support-payment-refund")
    assert "先不要重新收一次" in refund["phone_answer"]
    assert "不收集完整卡号" in refund["internal_notes"]
    assert "未经确认不宣告问题解决" in by_key("support-permission-privacy")["next_action"]


def test_content_hash_is_deterministic_and_binds_real_answer_and_version(monkeypatch):
    before = pack.canonical_pack_hash()
    assert re.fullmatch(r"[a-f0-9]{64}", before)
    assert pack.canonical_pack_hash() == before
    changed = copy.deepcopy(pack.BEAUTYOS_KNOWLEDGE_PACK)
    changed[0]["phone_answer"] += "（合成修订）"
    with monkeypatch.context() as patcher:
        patcher.setattr(pack, "BEAUTYOS_KNOWLEDGE_PACK", changed)
        assert pack.canonical_pack_hash() != before
    with monkeypatch.context() as patcher:
        patcher.setattr(pack, "PACK_VERSION", pack.PACK_VERSION + "-synthetic")
        assert pack.canonical_pack_hash() != before
    assert pack.canonical_pack_hash() == before
