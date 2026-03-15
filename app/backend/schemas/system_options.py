from pydantic import BaseModel
from typing import Optional

class SystemOptionBase(BaseModel):
    category: str
    key: str
    label: str
    order: Optional[int] = None
    is_enabled: Optional[bool] = True

class SystemOptionCreate(SystemOptionBase):
    pass

class SystemOptionUpdate(SystemOptionBase):
    category: Optional[str] = None
    key: Optional[str] = None
    label: Optional[str] = None

class SystemOption(SystemOptionBase):
    id: int

    class Config:
        from_attributes = True
