"""Strict, provider-neutral research requests and supported-claim outputs."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from ..web_evidence.models import SearchIntent


class ResearchContract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel)


class ResearchSpec(ResearchContract):
    query: str = Field(min_length=1, max_length=400)
    intent: SearchIntent = SearchIntent.academic_reference
    source_policy: Literal["attached_preferred", "attached_only", "external"] = "attached_preferred"
    max_sources: int = Field(default=5, ge=1, le=5)
    open_sources: int = Field(default=2, ge=0, le=2)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("A research question is required")
        return value


class ResearchClaim(ResearchContract):
    text: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(min_length=1, max_length=5)
    # The verifier can establish quoted evidence, not infer arbitrary semantic truth.
    support: Literal["quoted", "model_synthesis"] = "model_synthesis"


class ResearchSynthesis(ResearchContract):
    claims: list[ResearchClaim] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("limitations")
    @classmethod
    def bounded_limitations(cls, value: list[str]) -> list[str]:
        if any(len(item) > 1000 for item in value):
            raise ValueError("Limitations are too long")
        return value


class ResearchUnavailable(Exception):
    """Safe capability/error code; raw provider errors do not reach clients."""

    def __init__(self, code: str, *, retryable: bool = False):
        self.code, self.retryable = code, retryable
        super().__init__(code)
