from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BindingPreview(Strict):
    crm_subscription_id: int = Field(ge=1)
    stripe_subscription_id: str = Field(pattern=r"^sub_[A-Za-z0-9_]{1,220}$")
    sync_from: date
    income_type: Literal["management_fee", "website_fee", "ordering_fee", "other_income"]


class BindingConfirm(Strict):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    owner_verified: Literal[True]
    accepted_warning_codes: list[str] = Field(default_factory=list, max_length=20)


class BindingStatus(Strict):
    revision: int = Field(ge=1)
    status: Literal["active", "paused"]


class SyncInvoices(Strict):
    date_start: date
    date_end: date
    starting_after: str | None = Field(default=None, pattern=r"^in_[A-Za-z0-9_]{1,220}$")


class VerifyPilot(Strict):
    revision: int = Field(ge=1)
    owner_verified: Literal[True]
    verification_note: str = Field(min_length=3, max_length=2000)


class ActivateBulk(Strict):
    owner_verified: Literal[True]
    confirmation: Literal["启用批量绑定"]
    verification_note: str = Field(min_length=3, max_length=2000)


class ConfirmInvoice(Strict):
    revision: int = Field(ge=1)
    action: Literal["create_payment", "link_existing"]
    existing_payment_id: int | None = Field(default=None, ge=1)
    owner_verified: Literal[True]
    verification_note: str = Field(min_length=3, max_length=2000)
