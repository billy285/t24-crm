"""Normalize explicit merchant industry labels without inferring business type."""

from typing import Optional

from sqlalchemy import case, func, or_


UNCLASSIFIED_INDUSTRY = "__unclassified__"

# Keep Python normalization identical to the portable SQL filter expression.
# Only punctuation/spacing is ignored; there is no substring/name matching.
_IGNORED_CHARACTERS = " \t\r\n/／_-()（）·"


def _key(value: str) -> str:
    result = value.strip().lower()
    for character in _IGNORED_CHARACTERS:
        result = result.replace(character, "")
    return result


_RESTAURANT_ALIASES = {
    _key(value) for value in (
        "餐厅", "餐饮", "餐饮业", "餐饮行业", "中餐", "中餐厅", "中餐馆", "饭店", "饭馆", "餐馆",
        "restaurant", "restaurants", "chinese restaurant", "chinese restaurants",
        "food and beverage", "food & beverage", "food service", "dining",
    )
}
_BEAUTY_ALIASES = {
    _key(value) for value in (
        "美业", "美容", "美容院", "美容美发", "美发", "美发店", "美甲", "美甲店", "美睫", "美容美甲", "水疗", "按摩", "理发",
        "beauty", "beauty industry", "beauty salon", "beauty salons", "salon", "salons",
        "nail salon", "nail salons", "nails", "nail", "hair salon", "hair salons", "spa", "medspa", "med spa",
        "massage", "massage therapy", "massage salon", "barber", "barbershop", "lash salon",
        # Reviewed industry labels found in historical pool records. These are
        # exact aliases only; never inspect business names to assign a category.
        "Asian Massage", "Asian Massage/SPA", "Day Spa/按摩", "SPA/按摩", "Thai/Asian Massage", "中式按摩",
        "护肤/美容", "按摩/SPA", "无毒美甲沙龙", "日式美甲／美甲艺术", "美发/SPA", "美发/染发",
        "美发/理发/足疗", "美发/美容", "美发/美甲", "美发/美甲/SPA", "美容/Day Spa", "美容/Salon",
        "美甲/SPA", "美甲/护肤", "美甲/皮肤护理", "美甲/眉毛", "美甲/美容", "美甲/美容/护肤", "美甲工作室",
        "美甲／手足护理", "美甲／美容水疗", "美甲／美容沙龙", "美甲／美甲艺术", "足疗/SPA", "足疗/按摩",
    )
}
_UNCLASSIFIED_ALIASES = {
    _key(value) for value in ("", "待分类", "未分类", "未知", "unknown", "unclassified", "n/a", "none", "null", UNCLASSIFIED_INDUSTRY)
}


def normalize_merchant_industry(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    key = _key(stripped)
    if key in _RESTAURANT_ALIASES:
        return "餐厅"
    if key in _BEAUTY_ALIASES:
        return "美业"
    if key in _UNCLASSIFIED_ALIASES:
        return None
    # Explicit custom categories remain usable rather than being guessed or lost.
    return stripped


def merchant_industry_expression(column):
    """SQL canonical category, usable on legacy rows without a data backfill."""
    key = func.lower(func.trim(column))
    for character in _IGNORED_CHARACTERS:
        key = func.replace(key, character, "")
    return case(
        (key.in_(sorted(_RESTAURANT_ALIASES)), "餐厅"),
        (key.in_(sorted(_BEAUTY_ALIASES)), "美业"),
        (or_(column.is_(None), key.in_(sorted(_UNCLASSIFIED_ALIASES))), None),
        else_=func.trim(column),
    )


def merchant_industry_filter(column, value: str):
    expression = merchant_industry_expression(column)
    normalized = normalize_merchant_industry(value)
    return expression.is_(None) if normalized is None else expression == normalized


def merchant_industry_facets(grouped_counts) -> list[dict]:
    counts: dict[str, int] = {}
    for industry, count in grouped_counts:
        value = normalize_merchant_industry(industry) or UNCLASSIFIED_INDUSTRY
        counts[value] = counts.get(value, 0) + int(count)
    priority = {"餐厅": 0, "美业": 1, UNCLASSIFIED_INDUSTRY: 3}
    return [
        {"value": value, "label": "待分类" if value == UNCLASSIFIED_INDUSTRY else value, "count": count}
        for value, count in sorted(counts.items(), key=lambda item: (priority.get(item[0], 2), item[0]))
    ]
