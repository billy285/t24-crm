"""Conservative identity evidence shared by native and compatibility imports."""

import re


def normalized_identity_text(value) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)


def has_concrete_name_and_address(record) -> bool:
    name, address = (str(getattr(record, key, None) or "").strip() for key in ("business_name", "address"))
    unknown = {"", "unknown", "n/a", "na", "none", "null", "未知", "不详", "暂无", "未提供", "待确认", "待核验"}
    if name.casefold() in unknown or address.casefold() in unknown:
        return False
    # A descriptive hiring contact or an explicitly missing street is not a
    # physical merchant identity, even when many rows share the same label.
    placeholders = r"待核[验实]|待确认|待补[齐充]|未[知提供确认]|暂无|不详|(?i:unknown|pending\s+(?:verification|confirmation)|name\s+pending|address\s+pending)"
    if re.search(placeholders, name) or re.search(placeholders, address):
        return False
    return bool(normalized_identity_text(name) and normalized_identity_text(address))


def concrete_location_key(record) -> str | None:
    if not has_concrete_name_and_address(record):
        return None
    return f"location:{normalized_identity_text(record.business_name)}:{normalized_identity_text(record.address)}"
