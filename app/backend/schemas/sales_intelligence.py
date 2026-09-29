from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ContactDetails(StrictModel):
    reached_person: Literal["unknown", "gatekeeper", "decision_maker"] = "unknown"
    rejection_reason: str = Field(default="", max_length=200)
    need_summary: str = Field(default="", max_length=1000)
    next_step: str = Field(default="", max_length=1000)


class Stage(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=30)
    evidence: str = Field(min_length=1, max_length=180)
    stale_days: int = Field(default=7, ge=1, le=180)
    milestone: Literal[
        "none",
        "qualified",
        "scheduled",
        "demo",
        "quoted",
        "decision",
        "won",
        "handoff",
        "lost",
        "nurture",
    ] = "none"


class Pipeline(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=30)
    stages: list[Stage] = Field(min_length=2, max_length=15)

    @model_validator(mode="after")
    def unique(self):
        if len({x.key for x in self.stages}) != len(self.stages):
            raise ValueError("阶段标识不可重复")
        return self


class CustomField(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=30)
    required_milestones: list[
        Literal[
            "none",
            "qualified",
            "scheduled",
            "demo",
            "quoted",
            "decision",
            "won",
            "handoff",
            "lost",
            "nurture",
        ]
    ] = Field(default_factory=list, max_length=10)


class OperatingConfig(StrictModel):
    pipelines: list[Pipeline] = Field(min_length=1, max_length=8)
    custom_fields: list[CustomField] = Field(default_factory=list, max_length=12)
    weights: dict[str, int]
    repeated_rejection_count: int = Field(default=3, ge=2, le=20)
    unconnected_attempts: int = Field(default=5, ge=2, le=50)
    interest_stale_days: int = Field(default=14, ge=1, le=180)
    default_contact_start: int = Field(default=10, ge=0, le=23)
    default_contact_end: int = Field(default=18, ge=1, le=24)

    @model_validator(mode="after")
    def consistent(self):
        if (
            set(self.weights) != {"results", "pipeline", "execution", "quality"}
            or sum(self.weights.values()) != 100
            or any(v < 0 or v > 100 for v in self.weights.values())
        ):
            raise ValueError("四项权重必须合计 100，且每项在 0–100 之间")
        for collection in (self.pipelines, self.custom_fields):
            if len({x.key for x in collection}) != len(collection):
                raise ValueError("标识不可重复")
        if self.default_contact_end <= self.default_contact_start:
            raise ValueError("联系结束时间必须晚于开始时间")
        return self


class ConfigPublish(StrictModel):
    effective_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    config: OperatingConfig
    reason: str = Field(min_length=3, max_length=500)


class ProfileUpdate(StrictModel):
    revision: int = Field(ge=0)
    pipeline_key: str = Field(max_length=40)
    stage_key: str = Field(max_length=40)
    evidence: str = Field(min_length=3, max_length=2000)
    next_step: str = Field(default="", max_length=1000)
    next_step_date: date | None = None
    need_summary: str = Field(default="", max_length=1000)
    decision_maker: str = Field(default="", max_length=200)
    timezone: str = Field(default="", max_length=80)
    custom_fields: dict[str, str] = Field(default_factory=dict)
    potential_override: Literal["", "priority", "nurture", "unknown", "low_fit"] = ""
    override_reason: str = Field(default="", max_length=500)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        if value:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("请选择有效的 IANA 时区")
        return value

    @field_validator("custom_fields")
    @classmethod
    def fields_size(cls, value):
        if len(value) > 12 or any(
            len(k) > 40 or len(v) > 1000 for k, v in value.items()
        ):
            raise ValueError("自定义资料过长")
        return value


class TargetCreate(StrictModel):
    employee_id: int
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    previous_revision: int = Field(default=0, ge=0)
    role_template: Literal["full_cycle", "development", "closer"] = "full_cycle"
    calls: int = Field(ge=1, le=30000)
    qualified: int = Field(ge=1, le=10000)
    demos: int = Field(ge=1, le=10000)
    wins: int = Field(ge=1, le=10000)
    reason: str = Field(min_length=3, max_length=500)


class CoachingCreate(StrictModel):
    employee_id: int
    lead_id: int | None = None
    action: str = Field(min_length=3, max_length=2000)
    due_date: date


class CoachingComplete(StrictModel):
    revision: int
    completion_note: str = Field(min_length=3, max_length=2000)


class SavedViewCreate(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    filters: dict[str, str] = Field(default_factory=dict)

    @field_validator("filters")
    @classmethod
    def safe_filters(cls, value):
        allowed = {
            "search",
            "potential",
            "min_calls",
            "source",
            "industry",
            "owner",
            "signal",
            "stage",
            "sort",
        }
        if set(value) - allowed or any(len(v) > 200 for v in value.values()):
            raise ValueError("无效的筛选条件")
        return value
