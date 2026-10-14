"""Explicit sales enrichment request allowlist, separate from lead assignment."""
import re
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SalesEnrichmentContact(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    wechat: str | None = Field(default=None, max_length=120)
    verification: Literal["pending", "confirmed"] = "pending"

    @field_validator("name", "role", "phone", "email", "wechat")
    @classmethod
    def empty_to_none(cls, value):
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_contact(self):
        if not any((self.name, self.phone, self.email, self.wechat)):
            raise ValueError("联系人至少填写姓名或一种联系方式")
        if self.email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.email):
            raise ValueError("请填写有效的联系人邮箱")
        return self


class SalesEnrichmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    expected_lead_updated_at: datetime
    business_name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=1000)
    store_phone: str = Field(min_length=1, max_length=64)
    contacts: list[SalesEnrichmentContact] = Field(default_factory=list, max_length=20)
    preferred_contact_id: str | None = Field(default=None, max_length=64)
    interest_product_ids: list[int] = Field(default_factory=list, max_length=30)
    need_summary: str | None = Field(default=None, max_length=4000)
    best_contact_time: str | None = Field(default=None, max_length=300)
    verification: Literal["pending", "confirmed"] = "pending"
    source: Literal["call", "manual"] = "manual"

    @field_validator("industry", "city", "state", "country", "address", "website", "need_summary", "best_contact_time", "preferred_contact_id")
    @classmethod
    def empty_to_none(cls, value):
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_lists(self):
        ids = [item.id for item in self.contacts]
        if len(ids) != len(set(ids)):
            raise ValueError("联系人编号不能重复")
        if self.preferred_contact_id and self.preferred_contact_id not in ids:
            raise ValueError("首选联系人必须在本次联系人名单中")
        if len(self.interest_product_ids) != len(set(self.interest_product_ids)) or any(i <= 0 for i in self.interest_product_ids):
            raise ValueError("意向产品编号无效或重复")
        if self.website and ":" in self.website and not self.website.lower().startswith(("https://", "http://")):
            raise ValueError("网站仅支持 http 或 https 地址")
        return self


class SalesDialStartedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    phone: str = Field(min_length=1, max_length=64)
