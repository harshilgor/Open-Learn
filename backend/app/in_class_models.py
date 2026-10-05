from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .lecture_models import LectureCreate

class ClassPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    notes:bool=True
    materials:bool=True
    practice:bool=True
    flashcards:bool=False

class ClassCreate(BaseModel):
    model_config=ConfigDict(populate_by_name=True,extra='forbid')
    recording:LectureCreate
    device_id:str=Field(alias='deviceId',min_length=1,max_length=160)
    material_version_ids:list[str]=Field(default_factory=list,alias='materialVersionIds',max_length=20)
    policy:ClassPolicy=Field(default_factory=ClassPolicy)

class ClassCommand(BaseModel):
    model_config=ConfigDict(populate_by_name=True,extra='forbid')
    expected_revision:int=Field(alias='expectedRevision',ge=1)
    action:Literal['cancel_processing','resume_processing','retry','partial_package']
    output_id:str|None=Field(default=None,alias='outputId',max_length=160)

class GroundedBlock(BaseModel):
    title:str=Field(min_length=1,max_length=240)
    body:str=Field(min_length=1,max_length=4000)
    segmentIds:list[str]=Field(min_length=1,max_length=40)

class NotesOutput(BaseModel):
    blocks:list[GroundedBlock]=Field(min_length=1,max_length=12)

class RecallItem(BaseModel):
    prompt:str=Field(min_length=1,max_length=500)
    answer:str=Field(min_length=1,max_length=1500)
    segmentIds:list[str]=Field(min_length=1,max_length=40)

class RecallOutput(BaseModel):
    items:list[RecallItem]=Field(min_length=1,max_length=12)
