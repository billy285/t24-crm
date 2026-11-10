"""Human prospect quality, independent of sales opportunity or consent."""
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

QualityStatus = Literal['pending', 'valid', 'invalid_phone', 'not_target', 'closed']
EntityKind = Literal['pool', 'lead']


class ProspectCorrectedFields(BaseModel):
    model_config = ConfigDict(extra='forbid')
    business_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    address: Optional[str] = Field(default=None, max_length=500)
    contact_name: Optional[str] = Field(default=None, max_length=200)
    chinese_service: Literal['unknown', 'yes', 'no'] = 'unknown'

    @field_validator('business_name', 'address', 'contact_name')
    @classmethod
    def clean_text(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError('修正资料不可只含空格；未知请留空')
        return value


class ProspectVerificationUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0)
    status: QualityStatus
    method: Literal['call', 'source_review']
    notes: str = Field(min_length=1, max_length=4000)
    corrected_fields: ProspectCorrectedFields = Field(default_factory=ProspectCorrectedFields)

    @field_validator('notes')
    @classmethod
    def require_notes(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('请记录实际核验依据，不要填写空白备注')
        return value
