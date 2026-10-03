"""Concept-domain DTOs extend shared identity and capability contracts."""
from typing import Literal
from pydantic import Field, model_validator
from .shared_contracts import Capability, ConceptRecord, Contract, Identifier, Revision, RevisionRef


class ConceptCreate(Contract):
    title: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1, max_length=4000)
    aliases: tuple[str, ...] = Field(default=(), max_length=50)
    discipline: str = Field(min_length=1, max_length=200)
    expected_grain: str = Field(min_length=1, max_length=1000)
    examples: tuple[str, ...] = Field(default=(), max_length=20)


class StableConcept(ConceptRecord):
    title: str
    expected_grain: str
    examples: tuple[str, ...] = ()
    successor_ids: tuple[Identifier, ...] = ()
    retirement: Literal["merged", "split"] | None = None


class CourseMappingCreate(Contract):
    concept_id: Identifier
    course_id: Identifier
    outcome_id: Identifier
    wording: str = Field(min_length=1, max_length=1000)
    aliases: tuple[str, ...] = Field(default=(), max_length=50)
    scope: str = Field(min_length=1, max_length=2000)
    capability: Capability
    material_ids: tuple[Identifier, ...] = Field(default=(), max_length=50)


class RelationshipCreate(Contract):
    from_concept_id: Identifier
    to_concept_id: Identifier
    relationship: Literal["prerequisite", "part_of", "related", "commonly_confused_with"]
    rationale: str = Field(min_length=5, max_length=2000)
    source: RevisionRef | None = None
    origin: Literal["human", "model"] = "human"

    @model_validator(mode="after")
    def no_self(self):
        if self.from_concept_id == self.to_concept_id:
            raise ValueError("Self relationships are not allowed")
        return self


class ReviewCommand(Contract):
    expected_graph_revision: Revision
    decision: Literal["reviewed", "rejected"]
    rationale: str = Field(min_length=5, max_length=2000)


class LegacyMappingCreate(Contract):
    graph_id: Identifier
    graph_revision: Revision
    node_id: Identifier
    concept_id: Identifier
    rationale: str = Field(min_length=5, max_length=2000)
    expected_mapping_revision: Revision | None = None


class ConceptChange(Contract):
    expected_graph_revision: Revision
    kind: Literal["merge", "split"]
    source_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=20)
    target_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=20)
    rationale: str = Field(min_length=10, max_length=4000)

    @model_validator(mode="after")
    def shape(self):
        if len(set(self.source_ids)) != len(self.source_ids) or len(set(self.target_ids)) != len(self.target_ids) or set(self.source_ids) & set(self.target_ids):
            raise ValueError("Merge/split identities must be distinct")
        if self.kind == "merge" and len(self.target_ids) != 1:
            raise ValueError("A merge has one destination")
        if self.kind == "split" and (len(self.source_ids) != 1 or len(self.target_ids) < 2):
            raise ValueError("A split has one original and multiple destinations")
        return self


class MappingReport(Contract):
    concept_id: Identifier
    description: str = Field(min_length=5, max_length=3000)


class RubricConcept(Contract):
    concept_id: Identifier
    capability: Capability
    role: Literal["target", "prerequisite", "incidental"]
    relevance_weight: float = Field(gt=0, le=1)


class RubricCriterion(Contract):
    criterion_id: Identifier
    concepts: tuple[RubricConcept, ...] = Field(min_length=1, max_length=20)
    attribution: Literal["resolved", "ambiguous"] = "ambiguous"


class RubricMappingCreate(Contract):
    question_id: Identifier
    question_revision: Revision
    criteria: tuple[RubricCriterion, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def distinct(self):
        if len({c.criterion_id for c in self.criteria}) != len(self.criteria):
            raise ValueError("Rubric criterion IDs must be unique")
        return self
