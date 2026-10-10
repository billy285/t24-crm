from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SourceId = Literal["gmail", "google_ads", "bofa", "stripe", "manual"]
ActionStatus = Literal["open", "done", "snoozed", "archived"]
Priority = Literal["low", "normal", "high", "urgent"]


class PrivateItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: Literal["manual"] = "manual"
    kind: Literal["task", "note"] = "task"
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=6000)
    priority: Priority = "normal"
    amount_minor: int | None = Field(default=None, ge=-9_000_000_000_000_000, le=9_000_000_000_000_000, strict=True)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    occurred_at: datetime | None = None
    due_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("标题不能为空")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value):
        return value.upper() if value else None

    @field_validator("occurred_at", "due_at")
    @classmethod
    def normalize_datetime(cls, value):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

    @model_validator(mode="after")
    def amount_has_currency(self):
        if self.amount_minor is not None and not self.currency:
            raise ValueError("金额必须有币种")
        return self


class PrivateItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=240)
    summary: str | None = Field(default=None, max_length=6000)
    action_status: ActionStatus | None = None
    snoozed_until: datetime | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value):
        if value is not None and not value.strip():
            raise ValueError("标题不能为空")
        return value.strip() if value is not None else None

    @field_validator("snoozed_until")
    @classmethod
    def normalize_datetime(cls, value):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

    @model_validator(mode="after")
    def reject_null_fields(self):
        for name in ("title", "summary", "action_status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} 不能为空")
        return self


class PrivateSourceResponse(BaseModel):
    id: SourceId
    name: str
    status: str
    capabilities: list[str]
    missing_configuration: list[str]
    last_sync: datetime | None
    error: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PrivatePreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sync_interval_seconds: int = Field(ge=300, le=86400, strict=True)


class PrivateItemResponse(BaseModel):
    id: str
    source_id: SourceId
    kind: str
    title: str
    summary: str
    status: str
    priority: Priority
    amount_minor: int | None
    currency: str | None
    occurred_at: datetime | None
    due_at: datetime | None
    source_url: str | None
    evidence: dict[str, Any]
    action_status: ActionStatus
    snoozed_until: datetime | None
