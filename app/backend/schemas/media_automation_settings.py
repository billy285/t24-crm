from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,StrictBool,model_validator

Platform=Literal["google_business","facebook","instagram"]
Industry=Literal["restaurant","beauty","general"]
class Strict(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)

class Mix(Strict):
    featured:int=Field(ge=0,le=100)
    discovery:int=Field(ge=0,le=100)
    business:int=Field(ge=0,le=100)
    @model_validator(mode="after")
    def total(self):
        if self.featured+self.discovery+self.business!=100:raise ValueError("内容比例合计须为100%")
        return self

class PlanRules(Strict):
    weekdays:list[int]=Field(min_length=1,max_length=7)
    local_time:str=Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    language:Literal["en","zh_en"]
    include_prices:StrictBool
    forbidden_claims:list[str]=Field(max_length=20)
    content_mix:Mix
    tone:Literal["friendly","professional","lively"]
    @model_validator(mode="after")
    def unique_days(self):
        if len(set(self.weekdays))!=len(self.weekdays) or any(d<1 or d>7 for d in self.weekdays):raise ValueError("请选择不重复的周一至周日")
        if any(not w.strip() or len(w)>100 for w in self.forbidden_claims):raise ValueError("禁写内容每项1—100字")
        return self

class Overrides(Strict):
    weekdays:list[int]|None=None
    local_time:str|None=Field(None,pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    language:Literal["en","zh_en"]|None=None
    include_prices:StrictBool|None=None
    forbidden_claims:list[str]|None=None
    content_mix:Mix|None=None
    tone:Literal["friendly","professional","lively"]|None=None

class Document(Strict):
    industry:Industry
    timezone:str|None=Field(None,max_length=80)
    defaults:PlanRules
    platform_overrides:dict[Platform,Overrides]=Field(default_factory=dict)
    template_key:str|None=Field(None,max_length=80)
    template_revision:int|None=Field(None,ge=1)

class Preview(Strict):
    request_id:str=Field(min_length=36,max_length=36)
    kind:Literal["edit","copy"]
    month:str=Field(pattern=r"^20[0-9]{2}-(?:0[1-9]|1[0-2])$")
    customer_id:int=Field(ge=1)
    expected_revision:int=Field(ge=0)
    document:Document|None=None
    target_ids:list[int]=Field(default_factory=list,max_length=30)
    platforms:list[Platform]=Field(default_factory=list,max_length=3)
    groups:list[Literal["cadence","writing","content"]]=Field(default_factory=list,max_length=3)

class Apply(Strict):
    request_id:str=Field(min_length=36,max_length=36)
    preview_hash:str=Field(pattern=r"^[a-f0-9]{64}$")
    confirmed:StrictBool

class TemplateSave(Strict):
    request_id:str=Field(min_length=36,max_length=36)
    name:str=Field(min_length=1,max_length=80)
    document:Document
