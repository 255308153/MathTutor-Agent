from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RAGDocType = Literal["concept_note", "question_explanation", "mistake_pattern", "learning_strategy"]


class RAGDocument(BaseModel):
    doc_id: str
    doc_type: RAGDocType
    title: str
    content: str
    source: str
    concept_id: str | None = None
    question_id: str | None = None
    assist2017_question_id: int | None = None
    assist2017_concept_id: int | None = None
    canonical_mapping: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)


class RAGSearchResult(BaseModel):
    doc_id: str
    doc_type: RAGDocType
    title: str
    content: str
    source: str
    concept_id: str | None = None
    question_id: str | None = None
    assist2017_question_id: int | None = None
    assist2017_concept_id: int | None = None
    canonical_mapping: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
