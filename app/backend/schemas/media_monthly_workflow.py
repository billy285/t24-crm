from pydantic import BaseModel, ConfigDict, Field, StrictBool
from typing import Literal


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Picture(Input):
    item_id: int = Field(ge=1)
    image_version_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    rights_confirmed: StrictBool


class Prepare(Input):
    request_id: str = Field(min_length=36, max_length=36)
    expected_run_revision: int = Field(ge=1)
    expected_workflow_revision: int = Field(ge=0)
    items: list[Picture] = Field(min_length=1, max_length=31)
    facts_confirmed: StrictBool


class Review(Input):
    request_id: str = Field(min_length=36, max_length=36)
    expected_revision: int = Field(ge=1)
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: StrictBool


class Schedule(Input):
    request_id: str = Field(min_length=36, max_length=36)
    expected_revision: int = Field(ge=1)
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    publication_confirmed: StrictBool
    confirmation_version: Literal["monthly-publication-v1"]


class Cancel(Input):
    request_id: str = Field(min_length=36, max_length=36)
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=200)
