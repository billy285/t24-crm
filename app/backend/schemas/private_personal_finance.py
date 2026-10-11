"""Strict bounded input for manual personal books; amounts are integer fen."""
from datetime import date
import re
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_MINOR = 9_000_000_000_000
Minor = Annotated[int, Field(strict=True, ge=0, le=MAX_MINOR)]
PositiveMinor = Annotated[int, Field(strict=True, gt=0, le=MAX_MINOR)]
Name = Annotated[str, Field(min_length=1, max_length=40)]
Title = Annotated[str, Field(min_length=1, max_length=80)]
EntryKind = Literal["expense", "income", "transfer", "borrow", "lend", "repay", "collect"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def calendar_date_only(cls, value, info):
        if info.field_name.endswith("_date") and value is not None:
            if type(value) is date:
                return value
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError("日期应为 YYYY-MM-DD")
        return value

    @field_validator("*", mode="after")
    @classmethod
    def normalize(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if any(ord(c) < 32 and c not in "\n\t" for c in value):
                raise ValueError("文字含无效字符")
            return value
        if isinstance(value, date) and not date(2000, 1, 1) <= value <= date(2100, 12, 31):
            raise ValueError("日期超出范围")
        return value

    @model_validator(mode="after")
    def nonblank(self):
        for field in ("name", "counterparty", "icon"):
            if field in self.model_fields_set and getattr(self, field, None) == "":
                raise ValueError("名称不能为空")
        return self


class Patch(Input):
    nullable: ClassVar[set[str]] = set()

    @model_validator(mode="after")
    def not_null(self):
        if any(getattr(self, field) is None for field in self.model_fields_set if field not in self.nullable):
            raise ValueError("字段不能为空")
        return self


class CreateInput(Input):
    client_request_id: UUID


class BootstrapInput(CreateInput):
    pass


class CategoryCreate(CreateInput):
    name: Name
    kind: Literal["expense", "income"]
    icon: str = Field(default="circle", max_length=40, pattern=r"^[a-z0-9-]+$")
    active: bool = True
    sort_order: int = Field(default=0, strict=True, ge=0, le=10000)


class CategoryPatch(Patch):
    name: Name | None = None
    kind: Literal["expense", "income"] | None = None
    icon: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9-]+$")
    active: bool | None = None
    sort_order: int | None = Field(default=None, strict=True, ge=0, le=10000)


class CategoryReorder(Input):
    kind: Literal["expense", "income"]
    category_ids: list[UUID] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(self.category_ids) != len(set(self.category_ids)):
            raise ValueError("分类不能重复")
        return self


class AccountCreate(CreateInput):
    name: Name
    kind: Literal["cash", "bank", "wechat", "alipay"]
    currency: Literal["CNY"] = "CNY"
    opening_balance_minor: Minor = 0
    active: bool = True


class AccountPatch(Patch):
    name: Name | None = None
    kind: Literal["cash", "bank", "wechat", "alipay"] | None = None
    opening_balance_minor: Minor | None = None
    active: bool | None = None


class DebtCreate(CreateInput):
    name: Title
    direction: Literal["payable", "receivable"]
    principal_minor: PositiveMinor
    due_date: date | None = None
    installment_minor: PositiveMinor | None = None
    note: str = Field(default="", max_length=1000)


class DebtPatch(Patch):
    nullable: ClassVar[set[str]] = {"due_date", "installment_minor"}
    name: Title | None = None
    due_date: date | None = None
    installment_minor: PositiveMinor | None = None
    note: str | None = Field(default=None, max_length=1000)


class PlanCreate(CreateInput):
    name: Title
    category_id: UUID
    amount_minor: PositiveMinor
    due_date: date


class PlanPatch(Patch):
    name: Title | None = None
    category_id: UUID | None = None
    amount_minor: PositiveMinor | None = None
    due_date: date | None = None
    status: Literal["pending", "cancelled"] | None = None


class PlanPay(Input):
    amount_minor: PositiveMinor
    account_id: UUID
    entry_date: date
    note: str = Field(default="", max_length=1000)
    client_request_id: UUID


class GoalCreate(CreateInput):
    name: Title
    target_minor: PositiveMinor
    prepared_minor: Minor = 0
    target_date: date | None = None
    active: bool = True


class GoalPatch(Patch):
    nullable: ClassVar[set[str]] = {"target_date"}
    name: Title | None = None
    target_minor: PositiveMinor | None = None
    prepared_minor: Minor | None = None
    target_date: date | None = None
    active: bool | None = None


class BudgetPatch(Input):
    budget_minor: Minor | None


class EntryCreate(Input):
    kind: EntryKind
    amount_minor: PositiveMinor
    account_id: UUID
    to_account_id: UUID | None = None
    category_id: UUID | None = None
    debt_id: UUID | None = None
    counterparty: Title | None = None
    entry_date: date
    note: str = Field(default="", max_length=1000)
    client_request_id: UUID

    @model_validator(mode="after")
    def relationships(self):
        if self.kind in {"expense", "income"}:
            if not self.category_id or self.debt_id or self.to_account_id or self.counterparty:
                raise ValueError("收支需要对应分类")
        elif self.kind == "transfer":
            if not self.to_account_id or self.to_account_id == self.account_id or self.category_id or self.debt_id or self.counterparty:
                raise ValueError("转账需要两个不同账户")
        else:
            if self.to_account_id or self.category_id:
                raise ValueError("借还本金不计收入支出")
            if self.kind in {"repay", "collect"} and not self.debt_id:
                raise ValueError("归还和收回需要选择债务")
            if self.kind in {"borrow", "lend"} and not self.debt_id and not self.counterparty:
                raise ValueError("需要填写借款对象")
        return self


class EntryPatch(Patch):
    category_id: UUID | None = None
    entry_date: date | None = None
    note: str | None = Field(default=None, max_length=1000)
