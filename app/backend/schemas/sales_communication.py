"""Selected call facts and the one outcome used for sales workflow decisions."""
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator


CALL_OUTCOMES = {
    "recorded": "已记录沟通",
    "no_answer": "未接通",
    "callback": "待回访",
    "interested": "有意向",
    "appointment": "已预约",
    "not_now": "暂时不需要",
    "existing_provider": "已有服务商",
    "not_interested": "无意向",
    "do_not_contact": "禁止再联系",
}
ACTION_PRIORITY = ("appointment", "interested", "callback", "not_now", "existing_provider")
EXCLUSIVE_OUTCOMES = {"do_not_contact", "no_answer", "not_interested"}
NO_CONVERSATION_EVIDENCE = {"no_answer", "recorded"}


class SalesQuickNoteSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    label: StrictStr = Field(min_length=1, max_length=24)
    text: StrictStr = Field(min_length=1, max_length=1000)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        if not value.isprintable():
            raise ValueError("按钮名称不能包含换行或控制字符")
        return value

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if any(not char.isprintable() and char not in "\t\r\n" for char in value):
            raise ValueError("备注正文不能包含控制字符")
        return value


class SalesCallSelection(BaseModel):
    outcome: str
    outcomes: list[str] | None = Field(default=None, max_length=len(CALL_OUTCOMES) - 1)
    quick_notes: list[SalesQuickNoteSnapshot] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def validate_selections(self):
        selected = self.outcomes if self.outcomes is not None else [self.outcome]
        values = set(selected)
        if len(selected) != len(values) or len({item.id for item in self.quick_notes}) != len(self.quick_notes):
            raise ValueError("沟通记录选项不能重复")
        if self.outcome == "recorded":
            if self.outcomes or not self.quick_notes:
                raise ValueError("仅记录沟通时，请至少选择一条快捷备注并留空标准结果")
            return self
        if self.outcome not in values or "recorded" in values or values.difference(CALL_OUTCOMES):
            raise ValueError("请选择有效的通话结果")
        if len(values) > 1:
            if values & EXCLUSIVE_OUTCOMES or ("not_now" in values and values & {"interested", "appointment"}):
                raise ValueError("所选通话结果互相冲突")
            primary = next(key for key in ACTION_PRIORITY if key in values)
            if self.outcome != primary:
                raise ValueError("主要通话结果与已选结果不一致")
        return self

    def selection_snapshot(self):
        if self.outcomes is None and not self.quick_notes:
            return None
        return {"outcomes": [] if self.outcome == "recorded" else self.outcomes or [self.outcome],
                "quick_notes": [item.model_dump() for item in self.quick_notes]}


def activity_selections(activity):
    # Rows recorded before multi-select have only the authoritative single outcome.
    selection = getattr(activity, "communication_record", None) or {}
    outcomes = selection.get("outcomes", [activity.outcome])
    return {"outcomes": outcomes, "outcome_labels": [CALL_OUTCOMES.get(key, key) for key in outcomes],
            "quick_notes": selection.get("quick_notes", [])}
