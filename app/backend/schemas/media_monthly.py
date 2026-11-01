from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Facts(Input):
    public_name: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=300)
    highlights: list[str] = Field(min_length=1, max_length=20)


class Rules(Input):
    timezone: Literal["America/Chicago"]
    weekdays: list[int] = Field(min_length=3, max_length=3)
    local_time: Literal["11:00"]
    posts_per_week: Literal[3]
    language: Literal["en", "zh_en"]
    include_prices: StrictBool = False
    generic_mode: StrictBool = False
    forbidden_claims: list[str] = Field(default_factory=list, max_length=20)


class ImageChoice(Input):
    material_id: int = Field(ge=1)
    image_version_id: str | None = Field(None, pattern=r"^[a-f0-9]{32}$")
    menu_item_id: int | None = Field(None, ge=1)
    quality_confirmed: StrictBool = False


class ProfileInput(Input):
    expected_revision: int = Field(ge=0)
    public_facts: Facts
    rules: Rules
    menu_item_ids: list[int] = Field(default_factory=list, max_length=80)
    images: list[ImageChoice] = Field(min_length=1, max_length=20)
    confirmed_facts: StrictBool


class Consent(Input):
    confirmed: StrictBool
    notice_version: Literal["monthly-text-v1"]
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class Generate(Input):
    request_id: str = Field(min_length=36, max_length=36)
    expected_profile_revision: int = Field(ge=1)
    month: Literal["2026-11"]
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    consent: Consent


class EditItem(Input):
    expected_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=1500)
    owner_summary: str = Field(min_length=1, max_length=300)


class Adopt(Input):
    request_id: str = Field(min_length=36, max_length=36)
    expected_revision: int = Field(ge=1)
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: StrictBool
