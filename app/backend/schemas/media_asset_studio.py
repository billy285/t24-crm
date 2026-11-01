"""Strict, bounded local render recipes. No URLs, paths or executable settings."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=36, max_length=36)


class ProfileInput(StrictInput):
    expected_revision: int = Field(ge=0)
    preset: Literal["editorial", "clean", "warm"]
    brand_name: str = Field(min_length=1, max_length=60)
    primary_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    footer: str = Field(default="", max_length=120)


class JobInput(StrictInput):
    profile_revision: int = Field(ge=0)
    kind: Literal["poster", "collage", "enhance", "video"]
    image_ids: list[str] = Field(min_length=1, max_length=6)
    title: str = Field(default="", max_length=80)
    subtitle: str = Field(default="", max_length=160)
    format: Literal["square", "portrait", "landscape", "original"] = "square"
    exposure: float = Field(default=0, ge=-0.2, le=0.2, allow_inf_nan=False)
    color: float = Field(default=1, ge=0.8, le=1.2, allow_inf_nan=False)
    sharpness: float = Field(default=1, ge=0.8, le=1.2, allow_inf_nan=False)
    rights_confirmed: Literal[True]

    @field_validator("image_ids")
    @classmethod
    def valid_images(cls, value):
        if len(value) != len(set(value)) or any(not re.fullmatch(r"[a-f0-9]{32}", x) for x in value):
            raise ValueError("请选择不同的有效固定图片")
        return value


class RetryInput(StrictInput):
    expected_revision: int = Field(ge=1)


class AdoptInput(StrictInput):
    expected_revision: int = Field(ge=1)
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    title: str = Field(min_length=1, max_length=120)
    derivative_confirmed: Literal[True]
