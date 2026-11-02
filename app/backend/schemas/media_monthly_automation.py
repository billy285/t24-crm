from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class AutomationPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=36, max_length=36)
    expected_revision: int = Field(ge=0)
    enabled: StrictBool
    lead_days: int = Field(ge=3, le=14)
    local_time: Literal["09:00"] = "09:00"
    source_signature: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: StrictBool
    notice_version: Literal["monthly-autoprep-v1"]
