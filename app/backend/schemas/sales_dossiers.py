"""Only pre-sale dossier fields may cross this boundary."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class DossierSummaryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    need_summary: str = Field(default="", max_length=4000)
    objections: str = Field(default="", max_length=2000)
    promises: str = Field(default="", max_length=2000)
    next_step: str = Field(default="", max_length=2000)
    decision_maker: str = Field(default="", max_length=200)
    latest_conclusion: str = Field(default="", max_length=2000)
    next_action_at: datetime | None = None


class DossierInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: int = Field(gt=0)
    access: Literal["view", "collaborate"] = "view"
    expected_revision: int | None = Field(default=None, ge=0)


class DossierAck(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: str = Field(default="", max_length=2000)


class DossierRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
