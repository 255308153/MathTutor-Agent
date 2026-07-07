from __future__ import annotations

from typing import Literal

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
    keywords: list[str] = Field(default_factory=list)


class RAGSearchResult(BaseModel):
    doc_id: str
    doc_type: RAGDocType
    title: str
    content: str
    source: str
    concept_id: str | None = None
    question_id: str | None = None
    score: float = 0.0
