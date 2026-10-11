from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SourceId = Literal["gmail", "google_ads", "bofa", "bofa_bank", "stripe", "manual"]
ActionStatus = Literal["open", "done", "snoozed", "archived"]
Priority = Literal["low", "normal", "high", "urgent"]
MailBucket = Literal["urgent", "today", "digest", "low"]
MailFeedback = Literal["important", "not_relevant"]


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


class GmailPreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topics: list[Literal["finance", "ads", "security", "business"]] | None = Field(default=None, max_length=4)
    watch_senders: list[str] | None = Field(default=None, max_length=50)
    watch_keywords: list[str] | None = Field(default=None, max_length=30)
    muted_senders: list[str] | None = Field(default=None, max_length=50)

    @field_validator("watch_senders", "muted_senders")
    @classmethod
    def normalize_senders(cls, value):
        from services.private_mail_relevance import normalize_sender_rule
        return list(dict.fromkeys(normalize_sender_rule(item) for item in value)) if value is not None else None

    @field_validator("watch_keywords")
    @classmethod
    def normalize_keywords(cls, value):
        if value is None:
            return value
        if any(not 1 <= len(item.strip()) <= 80 or any(c in item for c in "\r\n") for item in value):
            raise ValueError("关键词应为 1–80 个字，不能包含换行")
        return list(dict.fromkeys(item.strip().casefold() for item in value))

    @field_validator("topics")
    @classmethod
    def unique_topics(cls, value):
        return list(dict.fromkeys(value)) if value is not None else None

    @model_validator(mode="after")
    def reject_null_fields(self):
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("关注设置不能为空，清空列表请使用 []")
        return self


class PrivatePreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sync_interval_seconds: int | None = Field(default=None, ge=300, le=86400, strict=True)
    gmail: GmailPreferencesPatch | None = None

    @model_validator(mode="after")
    def reject_null_fields(self):
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("设置不能为空")
        return self


class PrivateMailFeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feedback: MailFeedback | None
    apply_to_sender: bool = Field(default=False, strict=True)


class PrivateMailRelevance(BaseModel):
    bucket: MailBucket
    category: Literal["finance", "ads", "security", "business", "general", "promotion"]
    reasons: list[str]
    feedback: MailFeedback | None
    sender_address: str | None
    sender_verification: Literal["unverified"]


class PrivateMailTranslationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: list[str] = Field(min_length=1, max_length=10)

    @field_validator("item_ids")
    @classmethod
    def validate_ids(cls, value):
        from uuid import UUID
        for item_id in value:
            UUID(item_id)
        return list(dict.fromkeys(value))


class PrivateMailTranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["preview", "body"] = "body"


class PrivateMailTranslationResponse(BaseModel):
    state: Literal["ready", "failed", "pending", "unavailable"]
    title_zh: str | None = None
    summary_zh: str | None = None
    body_zh: str | None = None
    body_original: str | None = None
    body_available: bool = False
    truncated: bool = False
    updated_at: str | None = None


class PrivateMailBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["body"] = "body"


class PrivateWorkspaceBriefRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    period: Literal['today', 'last7days'] = 'today'
    snapshot_id: str = Field(pattern=r'^[a-f0-9]{64}$')


class PrivateStripeReportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    period: Literal['month', 'quarter', 'year', 'custom'] = 'month'
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    refresh: bool = Field(default=False, strict=True)


class PrivateBankCompleteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(pattern=r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')


class PrivateMailBriefDeadline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    at: None = None
    text: str | None = Field(default=None, max_length=240)
    confirmed: Literal[False] = False
    evidence: str | None = Field(default=None, max_length=1000)


class PrivateMailBriefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["ready", "failed", "pending", "unavailable"]
    title_zh: str | None = Field(default=None, max_length=1000)
    summary_zh: str | None = Field(default=None, max_length=3000)
    key_points: list[str] = Field(default_factory=list, max_length=3)
    relevance: str | None = Field(default=None, max_length=2000)
    next_action: str | None = Field(default=None, max_length=2000)
    needs_action: bool | None = None
    deadline: PrivateMailBriefDeadline | None = None
    importance: Literal["urgent", "today", "read", "uncertain"] = "uncertain"
    source_scope: Literal["body", "preview"] = "preview"
    source_evidence: list[str] = Field(default_factory=list, max_length=12)
    evidence_limited: bool = False
    original_body: str | None = Field(default=None, max_length=25000)
    truncated: bool = False
    updated_at: str | None = Field(default=None, max_length=80)
    provider_label: str = "AI 中文整理"
    code: str | None = Field(default=None, max_length=40)


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
    mail_relevance: PrivateMailRelevance | None = None
    mail_translation: PrivateMailTranslationResponse | None = None
    mail_brief: PrivateMailBriefResponse | None = None
