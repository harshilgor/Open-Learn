"""Public commands. Private solutions never share response models."""
from typing import Literal
from pydantic import Field
from .session_models import ApiModel

MAX_MATERIAL_BYTES = 500 * 1024 * 1024
MAX_DIRECT_MATERIAL_BYTES = 50 * 1024 * 1024
MATERIAL_UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024


class UploadRequest(ApiModel):
    title: str = Field(min_length=1, max_length=300)
    media_type: Literal["application/pdf", "text/plain", "text/markdown", "image/png", "image/jpeg", "image/webp", "image/gif"]
    byte_count: int = Field(gt=0, le=MAX_MATERIAL_BYTES)
    role: Literal["reference", "textbook", "lecture_notes", "sample_paper", "answer_key"] = "reference"
    course_id: str | None = None


class TextMaterial(ApiModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=100000)
    role: Literal["reference", "textbook", "lecture_notes", "sample_paper", "answer_key"] = "reference"
    course_id: str | None = None


class AttachMaterial(ApiModel):
    material_version_id: str


class PaperRequest(ApiModel):
    material_version_id: str


class PracticeRequest(ApiModel):
    blueprint_id: str
    blueprint_revision: int = Field(default=1, ge=1)
    count: int = Field(default=4, ge=1, le=20)
    mode: Literal["paper_match", "targeted_practice"] = "paper_match"
    session_id: str | None = None


class AttemptRequest(ApiModel):
    item_id: str
    response: str = Field(min_length=1, max_length=10000)


class AnswerRequest(ApiModel):
    response: str = Field(min_length=1, max_length=10000)
