"""Fact-bounded editorial direction and local-only copy review.

Directions are writing choices, never additional merchant facts or approval.
This module does no I/O, generation, scheduling or mutation.
"""
import re
from collections import defaultdict

VERSION = "monthly-editorial-v1"
CHANNELS = {
    "google_business": {
        "label": "Google 商家", "style": "自然、具体的门店产品介绍，正文约45—85个英文词，不堆砌标签。",
    },
    "facebook": {
        "label": "Facebook", "style": "商家口吻、自然对话，正文约40—80个英文词，可用至多2个相关标签。",
    },
    "instagram": {
        "label": "Instagram", "style": "商家口吻、简短开头和清楚分行，正文约25—60个英文词，可用至多3个相关标签。",
    },
}
ANGLES = (
    ("product_introduction", "让读者认识这个已确认产品，不重复罗列整家店的资料。"),
    ("menu_discovery", "介绍这个已确认菜单分类，帮助读者发现一种选餐方向。"),
    ("personal_choice", "围绕读者自己的选餐偏好展开，不替读者声称体验或效果。"),
    ("local_connection", "自然结合已确认的城市，介绍这个产品，不承诺距离、营业或即时供应。"),
    ("format_spotlight", "围绕已确认的餐品形式或服务类别介绍，不根据名字猜配料。"),
    ("shortlist", "给读者一个可收藏的菜单选择，只写本条已经确认的产品事实。"),
)
CTAS = ("question", "none", "save", "none", "menu_explore", "none")
PROCESS_LANGUAGE = re.compile(
    r"\b(?:confirmed (?:facts?|menu|information)|official menu (?:lists?|identifies?|includes?)|"
    r"merchant[ -]chosen theme|(?:no|not) .{0,35}inferred here|"
    r"(?:AI[ -]generated|internal (?:draft|review)|source fingerprint))\b|"
    r"已确认(?:事实|资料)|根据(?:已确认|官网)资料|商家选定主题|资料指纹|内部草稿|尚未发布",
    re.I,
)


def directions(snapshot):
    """One deterministic direction per existing slot; no new dates or menu IDs."""
    counts = defaultdict(int)
    first_positions = {}
    result = []
    for index, slot in enumerate(snapshot.get("slots", [])):
        identity = tuple(slot.get("menu_item_ids", []))
        occurrence = counts[identity]
        counts[identity] += 1
        first_positions.setdefault(identity, index)
        angle, explanation = ANGLES[(first_positions[identity] + occurrence) % len(ANGLES)]
        result.append({"slot_id": slot["slot_id"], "angle": angle,
                       "direction": explanation, "cta": CTAS[index % len(CTAS)]})
    return result


def instructions(platform):
    channel = CHANNELS.get(platform, CHANNELS["google_business"])
    return (
        f"发布平台为{channel['label']}。{channel['style']}"
        "这是面向消费者的真实社交文案草稿，不是资料核对报告。"
        "用商家口吻写，不把'官网列有'、'已确认事实'、'商家选定主题'、AI流程或禁写规则写进公开正文。"
        "editorial_plan仅决定写作角度，不是新增事实或供应承诺；每条仍只引用本slot已确认菜品和公开事实。"
        "cta=question时才以一个自然问题收尾；none无需号召；save可建议收藏；"
        "menu_explore可邀请了解该分类，不添加链接、电话号码或未确认的下单方式。"
        "不同篇目使用不同开头和结构，重复出现的产品换用不同角度，不重复整段店铺介绍。"
        "可以改变表达方式，但不能新增配料、味道、份量、制作方式、优惠、营业时间、排名或效果。"
        "owner_summary只用于中文内部核对，不进入公开正文。"
    )


def _normalized(value):
    value = re.sub(r"https?://\S+|#[\w\u4e00-\u9fff]+", " ", str(value).lower())
    return " ".join(re.findall(r"[\w\u4e00-\u9fff]+", value))


def _phrases(value):
    words = value.split()
    if len(words) >= 8:
        return {tuple(words[index:index + 4]) for index in range(len(words) - 3)}
    return {value[index:index + 5] for index in range(max(0, len(value) - 4))}


def review(items):
    """Hints only. Preserve all existing review/approval/dispatch conditions."""
    warnings = defaultdict(list)
    normalized = [_normalized(item.get("content", "")) for item in items]
    phrases = [_phrases(value) for value in normalized]
    duplicates = []
    for index, value in enumerate(normalized):
        for previous in range(index):
            other = normalized[previous]
            union = phrases[index] | phrases[previous]
            similar = bool(union) and len(phrases[index] & phrases[previous]) / len(union) >= 0.72
            if value and other and (value == other or min(len(value), len(other)) >= 80 and similar):
                duplicates.append((previous, index))
                warnings[str(items[index]["id"])].append(f"与第{previous + 1}篇表达相近，请检查是否需要换一个角度。")
                break
    process_count = 0
    for item in items:
        if PROCESS_LANGUAGE.search(str(item.get("content", ""))):
            process_count += 1
            warnings[str(item["id"])].append("正文含资料核对或内部流程用语，建议改成面向顾客的表达。")
    summary = []
    if duplicates:
        summary.append(f"有{len(duplicates)}篇与前文表达相近，可调整开头、角度或互动方式。")
    if process_count:
        summary.append(f"有{process_count}篇含内部流程用语，发布前请润色。")
    return {"version": VERSION, "needs_review": bool(summary), "duplicate_groups": len(duplicates),
            "process_language_items": process_count, "warnings": summary, "item_warnings": dict(warnings)}
