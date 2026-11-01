from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal
from uuid import UUID


class RequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=36, max_length=36)

    @field_validator("request_id")
    @classmethod
    def uuid(cls, value):
        if str(UUID(value)) != value: raise ValueError("请求编号格式不正确")
        return value


class Discover(RequestInput):
    connection_id: int = Field(ge=1)
    customer_id: int | None = Field(None, ge=1)


class Pair(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    customer_id: int = Field(ge=1)
    location_name: str = Field(pattern=r"^accounts/[0-9]+/locations/[0-9]+$", max_length=200)


class Preview(RequestInput):
    catalog_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    expected_catalog_revision: int = Field(ge=1)
    items: list[Pair] = Field(min_length=1, max_length=50)


class ConfirmedRequest(RequestInput):
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_boolean(cls, value):
        if value is not True: raise ValueError("请明确确认当前操作")
        return value


class Confirm(ConfirmedRequest):
    expected_revision: int = Field(ge=1)
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed_item_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("confirmed_item_ids")
    @classmethod
    def ids(cls, value):
        import re
        if len(set(value)) != len(value) or any(not re.fullmatch(r"[a-f0-9]{32}", x) for x in value): raise ValueError("请逐项确认当前预检")
        return value


class Cancel(ConfirmedRequest):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=200)
