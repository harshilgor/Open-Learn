from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Contract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid', str_strip_whitespace=True)

class SourceRef(Contract):
    kind: Literal['note','lesson','material','quiz_attempt','lecture']
    id: str = Field(min_length=1,max_length=160)
    revision: int = Field(ge=1)
    start_offset: int | None = Field(default=None,alias='startOffset',ge=0)
    end_offset: int | None = Field(default=None,alias='endOffset',ge=1)
    span_id: str | None = Field(default=None,alias='spanId',max_length=160)
    recording_id: str | None = Field(default=None,alias='recordingId',max_length=160)

class FlashcardRequest(Contract):
    session_id: str = Field(alias='sessionId',min_length=1,max_length=160)
    course_id: str | None = Field(default=None,alias='courseId',max_length=160)
    origin: Literal['conversation','ask','learn','quiz','in_class','review'] = 'conversation'
    source_refs: list[SourceRef] = Field(alias='sourceRefs',min_length=1,max_length=20)
    objective: str = Field(default='Practice covered concepts',max_length=1000)
    requested_count: int = Field(default=12,alias='requestedCount',ge=1,le=60)
    card_types: list[Literal['qa','cloze']] = Field(default=['qa','cloze'],alias='cardTypes',min_length=1,max_length=2)
    target_deck_id: str | None = Field(default=None,alias='targetDeckId',max_length=160)
    expected_deck_revision: int | None = Field(default=None,alias='expectedDeckRevision',ge=1)
    client_command_id: str = Field(alias='clientCommandId',min_length=1,max_length=160)

class ImageMask(Contract):
    x: float = Field(ge=0,le=1)
    y: float = Field(ge=0,le=1)
    width: float = Field(gt=0,le=1)
    height: float = Field(gt=0,le=1)
    @model_validator(mode='after')
    def bounds(self):
        if self.x+self.width>1 or self.y+self.height>1:raise ValueError('Image mask must stay within the image.')
        return self

class CardImage(Contract):
    version_id: str = Field(alias='versionId',min_length=1,max_length=160)
    alt_text: str = Field(alias='altText',min_length=3,max_length=500)
    rights_confirmed: bool = Field(alias='rightsConfirmed')
    masks: list[ImageMask] = Field(default_factory=list,max_length=20)

class CardContent(Contract):
    type: Literal['qa','cloze','image_label','image_occlusion'] = 'qa'
    prompt: str = Field(min_length=3,max_length=1000)
    answer: str = Field(min_length=1,max_length=2000)
    explanation: str = Field(default='',max_length=3000)
    source_ids: list[str] = Field(alias='sourceIds',min_length=1,max_length=20)
    support_quote: str = Field(alias='supportQuote',min_length=1,max_length=2500)
    concept_ids: list[str] = Field(default_factory=list,alias='conceptIds',max_length=20)
    image: CardImage | None = None
    @model_validator(mode='after')
    def cloze(self):
        if self.type=='cloze':
            import re
            matches=re.findall(r'\{\{c1::([^{}]+)\}\}',self.prompt)
            if len(matches)!=1 or matches[0].strip()!=self.answer.strip():raise ValueError('Cloze requires one c1 deletion matching the answer.')
        if self.type in {'image_label','image_occlusion'}:
            if not self.image or not self.image.rights_confirmed:raise ValueError('Visual cards require an owned image, alternative description and source-use confirmation.')
            if self.type=='image_occlusion' and not self.image.masks:raise ValueError('Occlusion cards require a mask.')
        return self

class Generated(Contract):
    cards: list[CardContent] = Field(min_length=1,max_length=12)

class DeckCommand(Contract):
    command_id: str = Field(alias='commandId',min_length=1,max_length=160)
    expected_revision: int = Field(alias='expectedRevision',ge=1)
    action: Literal['create','edit','publish','archive','restore','delete','suspend','activate','remove','reset_schedule','accept_candidate','dismiss_candidate','rename']
    card_id: str | None = Field(default=None,alias='cardId',max_length=160)
    candidate_id: str | None = Field(default=None,alias='candidateId',max_length=160)
    card_ids: list[str] = Field(default_factory=list,alias='cardIds',max_length=200)
    content: CardContent | None = None
    title: str | None = Field(default=None,min_length=1,max_length=240)
    reset_schedule: bool = Field(default=False,alias='resetSchedule')

class ReviewCreate(Contract):
    command_id: str = Field(alias='commandId',min_length=1,max_length=160)
    deck_id: str | None = Field(default=None,alias='deckId',max_length=160)
    course_id: str | None = Field(default=None,alias='courseId',max_length=160)
    practice: bool = False
    limit: int = Field(default=20,ge=1,le=100)
    timezone: str = Field(default='UTC',max_length=100)

class ReviewCommand(Contract):
    command_id: str = Field(alias='commandId',min_length=1,max_length=160)
    expected_revision: int = Field(alias='expectedRevision',ge=1)
    attempt_id: str = Field(alias='attemptId',min_length=1,max_length=160)
    action: Literal['reveal','rate','skip']
    rating: Literal['again','hard','good','easy'] | None = None
    response: str = Field(default='',max_length=4000)

class Preferences(Contract):
    proactive_drafts: bool = Field(default=False,alias='proactiveDrafts')
    reminders: bool = False
    timezone: str = Field(default='UTC',max_length=100)

class RefreshCommand(Contract):
    command_id: str = Field(alias='commandId',min_length=1,max_length=160)
    expected_revision: int = Field(alias='expectedRevision',ge=1)
