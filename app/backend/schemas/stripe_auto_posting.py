from typing import Literal
from pydantic import Field
from schemas.stripe_history_reconciliation import Strict


class TrialBindings(Strict):
    binding_ids: list[int] = Field(min_length=3, max_length=5)
    owner_verified: Literal[True]
    owner_note: str = Field(default="老板授权首批订阅只读模拟验证", min_length=3, max_length=1000)


class UpdateAutomaticPolicy(Strict):
    enabled: bool
    revision: int = Field(ge=0)
    owner_verified: Literal[True]
    owner_note: str = Field(min_length=3, max_length=1000)
