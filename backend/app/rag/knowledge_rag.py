from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol

from .schema import RAGDocument, RAGSearchResult


RAG_PATH = Path(__file__).resolve().parents[3] / "data" / "rag" / "demo_knowledge.json"


class KnowledgeRAG(Protocol):
    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> list[RAGSearchResult]:
        """Retrieve explanation evidence without mutating KT facts."""


class LocalKnowledgeRAG:
    @cached_property
    def documents(self) -> list[RAGDocument]:
        raw_documents = json.loads(RAG_PATH.read_text(encoding="utf-8"))
        return [RAGDocument.model_validate(document) for document in raw_documents]

    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> list[RAGSearchResult]:
        filters = filters or {}
        candidates = [
            document for document in self.documents if self._matches_filters(document, filters)
        ]
        results = [
            self._to_result(document, self._score(document, query))
            for document in candidates
        ]
        results.sort(key=lambda result: (-result.score, result.doc_id))
        return [result for result in results if result.score > 0][:limit] or results[:limit]

    def _matches_filters(self, document: RAGDocument, filters: dict[str, Any]) -> bool:
        doc_type = filters.get("doc_type")
        if doc_type and document.doc_type != doc_type:
            return False
        doc_types = filters.get("doc_types")
        if doc_types and document.doc_type not in set(doc_types):
            return False
        concept_id = filters.get("concept_id")
        if concept_id and document.concept_id != concept_id:
            return False
        question_id = filters.get("question_id")
        if question_id and document.question_id != question_id:
            return False
        return True

    def _score(self, document: RAGDocument, query: str) -> float:
        query_terms = self._terms(query)
        if not query_terms:
            return 0.1
        haystack = self._terms(
            " ".join([document.title, document.content, " ".join(document.keywords)])
        )
        overlap = len(query_terms & haystack)
        keyword_bonus = sum(1 for keyword in document.keywords if keyword in query)
        return round(overlap + keyword_bonus * 0.5, 4)

    def _terms(self, text: str) -> set[str]:
        normalized = (
            text.lower()
            .replace("，", " ")
            .replace("。", " ")
            .replace("？", " ")
            .replace("?", " ")
            .replace(",", " ")
            .replace(".", " ")
        )
        terms = {term.strip() for term in normalized.split() if term.strip()}
        for keyword in ("分数", "通分", "方程", "面积", "比例", "乘法", "口诀", "记忆", "错因", "策略", "推荐"):
            if keyword in normalized:
                terms.add(keyword)
        return terms

    def _to_result(self, document: RAGDocument, score: float) -> RAGSearchResult:
        return RAGSearchResult(
            doc_id=document.doc_id,
            doc_type=document.doc_type,
            title=document.title,
            content=document.content,
            source=document.source,
            concept_id=document.concept_id,
            question_id=document.question_id,
            score=score,
        )


knowledge_rag = LocalKnowledgeRAG()
