from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .lecture_models import LectureCreate

class ClassPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    notes:bool=True
    materials:bool=True
    practice:bool=False
    flashcards:bool=False
    noteDensity:Literal['concise','standard','detailed']='standard'
    practiceCadence:Literal['off','every_10_minutes','every_20_minutes','at_end']|None=None
    followProfessor:Literal['off','explicit','all']='explicit'
    showInterimTranscript:bool=True
    transcriptFontScale:Literal['small','standard','large']='standard'
    autoScrollLock:bool=True
    keepAudio:bool|None=None
    buddyQuietDuringClass:bool=False

class ClassCreate(BaseModel):
    model_config=ConfigDict(populate_by_name=True,extra='forbid')
    recording:LectureCreate
    device_id:str=Field(alias='deviceId',min_length=1,max_length=160)
    capture_capability:str|None=Field(default=None,alias='captureCapability',min_length=32,max_length=128)
    material_version_ids:list[str]=Field(default_factory=list,alias='materialVersionIds',max_length=20)
    policy:ClassPolicy=Field(default_factory=ClassPolicy)

class ClassCommand(BaseModel):
    model_config=ConfigDict(populate_by_name=True,extra='forbid')
    expected_revision:int=Field(alias='expectedRevision',ge=1)
    action:Literal['cancel_processing','resume_processing','retry','partial_package','update_policy']
    output_id:str|None=Field(default=None,alias='outputId',max_length=160)
    policy:ClassPolicy|None=None

class ClassMaterialAttach(BaseModel):
    model_config=ConfigDict(populate_by_name=True,extra='forbid')
    expected_revision:int=Field(alias='expectedRevision',ge=1)
    need_id:str=Field(alias='needId',min_length=1,max_length=160)
    version_id:str=Field(alias='versionId',min_length=1,max_length=160)

class ClassMaterialIntakeCreate(BaseModel):
    model_config=ConfigDict(populate_by_name=True,extra='forbid')
    expected_revision:int=Field(alias='expectedRevision',ge=1)
    command_id:str=Field(alias='commandId',min_length=8,max_length=160,pattern=r'^[A-Za-z0-9_.:-]+$')
    source_kind:Literal['upload','url','drive','canvas']=Field(alias='sourceKind')
    title:str|None=Field(default=None,min_length=1,max_length=300)
    media_type:Literal['application/pdf','text/plain','text/markdown']|None=Field(default=None,alias='mediaType')
    byte_count:int|None=Field(default=None,alias='byteCount',gt=0,le=500*1024*1024)
    url:str|None=Field(default=None,min_length=8,max_length=2048)
    connection_id:str|None=Field(default=None,alias='connectionId',min_length=1,max_length=160)
    file_id:str|None=Field(default=None,alias='fileId',min_length=1,max_length=300)
    entity_id:str|None=Field(default=None,alias='entityId',min_length=1,max_length=160)

class ClassLiveTranscriptSegmentCreate(BaseModel):
    model_config=ConfigDict(populate_by_name=True,extra='forbid')
    stream_id:str=Field(alias='streamId',min_length=32,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')
    stream_sequence:int=Field(alias='streamSequence',ge=1,le=2_147_483_647)
    provider_item_id:str=Field(alias='providerItemId',min_length=1,max_length=160)
    transcript:str=Field(min_length=1,max_length=6000)
    transcription_version:int=Field(default=1,alias='transcriptionVersion',ge=1,le=1000000)
    start_ms:int|None=Field(default=None,alias='startMs',ge=0,le=24*60*60*1000)
    end_ms:int|None=Field(default=None,alias='endMs',ge=0,le=24*60*60*1000)

    @model_validator(mode='after')
    def validate_recording_interval(self):
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError('startMs and endMs must be provided together.')
        if self.start_ms is not None and self.end_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError('endMs must be greater than startMs.')
        return self

class ClassLiveTranscriptInterimUpdate(BaseModel):
    model_config=ConfigDict(populate_by_name=True,extra='forbid')
    stream_id:str=Field(alias='streamId',min_length=32,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')
    provider_item_id:str=Field(alias='providerItemId',min_length=1,max_length=160)
    update_revision:int=Field(alias='updateRevision',ge=1,le=1000000)
    transcript:str=Field(min_length=1,max_length=6000)

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
