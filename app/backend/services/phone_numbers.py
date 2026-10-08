"""Strict, non-destructive phone parsing shared by import, matching and dialing.

The caller must supply a known country for national numbers.  Raw input is never
rewritten, and extensions are deliberately excluded from the identity key.
"""
from dataclasses import asdict, dataclass
import re
import unicodedata
from typing import Literal, Optional

import phonenumbers

PhoneStatus = Literal["valid", "invalid", "ambiguous", "needs_country", "empty"]
_COUNTRY_ALIASES = {
    "USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US", "美国": "US",
    "CANADA": "CA", "加拿大": "CA", "UK": "GB", "UNITED KINGDOM": "GB", "英国": "GB",
    "CHINA": "CN", "中国": "CN", "AUSTRALIA": "AU", "澳大利亚": "AU",
    "NEW ZEALAND": "NZ", "新西兰": "NZ", "HONG KONG": "HK", "香港": "HK",
    "TAIWAN": "TW", "台湾": "TW", "SINGAPORE": "SG", "新加坡": "SG",
}
_EXTENSION = re.compile(r"\s*(?:;ext=|\bext(?:ension)?\.?\s*[:=]?|x|#|分机\s*[:：]?)\s*(\d{1,10})\s*$", re.I)
_PHONE_TEXT = re.compile(r"^\+?[0-9\s().\-]+$")


@dataclass(frozen=True)
class PhoneNumberResult:
    raw: str
    e164: Optional[str] = None
    extension: Optional[str] = None
    status: PhoneStatus = "invalid"
    reason: str = "电话号码格式不正确"
    country: Optional[str] = None
    national_display: Optional[str] = None
    international_display: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_phone_country(country: Optional[str]) -> Optional[str]:
    value = str(country or "").strip().upper()
    value = _COUNTRY_ALIASES.get(value, value)
    return value if value in phonenumbers.SUPPORTED_REGIONS else None


def parse_phone_number(raw: Optional[str], country: Optional[str] = None) -> PhoneNumberResult:
    original = str(raw) if raw is not None else ""
    text = unicodedata.normalize("NFKC", original).strip()
    region = normalize_phone_country(country)
    if not text:
        return PhoneNumberResult(original, status="empty", reason="请填写电话号码", country=region)
    extension = None
    match = _EXTENSION.search(text)
    if match:
        extension = match.group(1)
        text = text[:match.start()].strip()
    if re.search(r"[/,;|&\n\r]", text) or text.count("+") > 1:
        return PhoneNumberResult(original, extension=extension, status="ambiguous", reason="请只填写一个电话号码，分机请单独标明", country=region)
    if not _PHONE_TEXT.fullmatch(text) or not re.search(r"\d", text):
        return PhoneNumberResult(original, extension=extension, reason="电话号码含有无法识别的字符", country=region)
    if not text.startswith("+") and not region:
        return PhoneNumberResult(original, extension=extension, status="needs_country", reason="本地号码需要明确国家或地区；也可填写以 + 开头的国际号码", country=region)
    try:
        parsed = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException:
        return PhoneNumberResult(original, extension=extension, reason="无法识别电话号码，请核对国家码和位数", country=region)
    if not phonenumbers.is_valid_number(parsed):
        return PhoneNumberResult(original, extension=extension, reason="电话号码无效，请核对国家码和位数", country=region)
    # Parsing an IDD prefix is allowed only with an explicitly known region.
    return PhoneNumberResult(
        original, e164=phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
        extension=extension, status="valid", reason="",
        country=phonenumbers.region_code_for_number(parsed) or region,
        national_display=phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL),
        international_display=phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
    )


def phone_match_key(raw: Optional[str], country: Optional[str] = None) -> Optional[str]:
    return parse_phone_number(raw, country).e164
