"""Typed reviewed actions. Owner, credentials and permission are not model input."""
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')

class Mail(Strict):
    to:list[str]=Field(min_length=1,max_length=5)
    cc:list[str]=Field(default_factory=list,max_length=5)
    subject:str=Field(min_length=1,max_length=200)
    body:str=Field(min_length=1,max_length=10000)
    attachmentIds:list[str]=Field(default_factory=list,max_length=3)
    @field_validator('to','cc')
    @classmethod
    def addresses(cls,items):
        import re
        if any(not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', item) or len(item)>254 for item in items):raise ValueError('Use plain email addresses without display names.')
        if len(set(items))!=len(items):raise ValueError('Duplicate recipients.')
        return items
    @field_validator('subject')
    @classmethod
    def header(cls,value):
        if any(ord(c)<32 for c in value):raise ValueError('Invalid mail header.')
        return value

class Event(Strict):
    calendarId:str=Field(min_length=1,max_length=300)
    eventId:str|None=Field(default=None,max_length=300)
    summary:str=Field(min_length=1,max_length=200)
    description:str=Field(default='',max_length=10000)
    start:datetime
    end:datetime
    timeZone:str=Field(max_length=100)
    attendees:list[str]=Field(default_factory=list,max_length=10)
    sendUpdates:Literal['none','all']='none'
    @model_validator(mode='after')
    def times(self):
        try:ZoneInfo(self.timeZone)
        except (ZoneInfoNotFoundError, ValueError):raise ValueError('Specify a valid IANA timezone.') from None
        if self.start.utcoffset() is None or self.end.utcoffset() is None or self.end<=self.start:raise ValueError('Specify timezone-aware start/end times in order.')
        Mail.addresses(self.attendees)
        return self

class Draft(Strict):
    connectionId:str=Field(min_length=1,max_length=160)
    expectedTaskRevision:int=Field(ge=1)
    kind:Literal['gmail_send','calendar_create','calendar_update']
    mail:Mail|None=None
    event:Event|None=None
    @model_validator(mode='after')
    def body_shape(self):
        if (self.kind=='gmail_send')!=(self.mail is not None) or (self.kind!='gmail_send')!=(self.event is not None):raise ValueError('Supply exactly the matching action body.')
        if self.event and ((self.kind=='calendar_update')!=(self.event.eventId is not None)):raise ValueError('Updates require an event ID; creates cannot choose one.')
        return self

class Decision(Strict):
    decision:Literal['approve','reject']
    expectedRevision:int=Field(ge=1)
    actionHash:str=Field(min_length=64,max_length=64)

class OAuthStart(Strict):
    capabilities:list[Literal['drive_read','gmail_read','gmail_send','calendar_write']]=Field(min_length=1,max_length=4)

class ChildRequest(Strict):
    expectedRevision:int=Field(ge=1)
    kind:Literal['research','lab_analysis']
    assignment:str=Field(min_length=1,max_length=400)

class StandingGrant(Strict):
    connectionId:str=Field(min_length=1,max_length=160)
    kind:Literal['gmail_send','calendar_create','calendar_update']
    allowedRecipients:list[str]=Field(default_factory=list,max_length=10)
    calendarId:str|None=Field(default=None,max_length=300)
    maxActions:int=Field(ge=1,le=10)
    expiresAt:datetime
    @model_validator(mode='after')
    def constrained(self):
        Mail.addresses(self.allowedRecipients)
        if self.expiresAt.utcoffset() is None:raise ValueError('Grant expiry needs a timezone.')
        if self.kind=='gmail_send' and not self.allowedRecipients:raise ValueError('Specify recipient constraints.')
        if self.kind!='gmail_send' and not self.calendarId:raise ValueError('Specify one calendar.')
        return self

class ConnectorError(Exception):
    def __init__(self,code,uncertain=False):self.code,self.uncertain=code,uncertain;super().__init__(code)
