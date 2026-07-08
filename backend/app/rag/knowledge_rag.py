from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol

from ..mapping.assist2017_mapping import CanonicalMappingRepository, DEFAULT_MAPPING_PATH
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
        return [
            self._with_canonical_metadata(RAGDocument.model_validate(document))
            for document in raw_documents
        ]

    @cached_property
    def canonical_mapping(self) -> CanonicalMappingRepository | None:
        if not DEFAULT_MAPPING_PATH.is_file():
            return None
        return CanonicalMappingRepository.from_path(DEFAULT_MAPPING_PATH)

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
        assist_question_id = filters.get("assist2017_question_id")
        if assist_question_id and str(document.assist2017_question_id) != str(assist_question_id):
            return False
        assist_concept_id = filters.get("assist2017_concept_id")
        if assist_concept_id and str(document.assist2017_concept_id) != str(assist_concept_id):
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
            assist2017_question_id=document.assist2017_question_id,
            assist2017_concept_id=document.assist2017_concept_id,
            canonical_mapping=document.canonical_mapping,
            provenance=document.provenance,
            coverage=document.coverage,
            score=score,
        )

    def _with_canonical_metadata(self, document: RAGDocument) -> RAGDocument:
        repository = self.canonical_mapping
        question_mapping = None
        concept_mapping = None
        if repository is not None and document.question_id:
            question_mapping = repository.get_by_mathtutor_question_id(document.question_id)
        if repository is not None and document.concept_id:
            concept_mapping = repository.concept_for_mathtutor_concept_id(document.concept_id)

        assist_question_id = document.assist2017_question_id
        assist_concept_id = document.assist2017_concept_id
        canonical_mapping: dict[str, Any] = dict(document.canonical_mapping)
        if question_mapping is not None:
            assist_question_id = question_mapping.assist2017_question_id
            assist_concept_id = question_mapping.assist2017_concept_id
            canonical_mapping.update(
                {
                    "question_id": question_mapping.question_id,
                    "concept_id": question_mapping.concept_id,
                    "concept_name": question_mapping.concept_name,
                    "teaching_type": question_mapping.teaching_type,
                    "assist2017_question_id": question_mapping.assist2017_question_id,
                    "assist2017_concept_id": question_mapping.assist2017_concept_id,
                    "q_matrix_reference": question_mapping.q_matrix_reference.model_dump(),
                    "source": question_mapping.source_provenance.source,
                }
            )
        elif concept_mapping is not None:
            assist_concept_id = concept_mapping.assist2017_concept_id
            canonical_mapping.update(
                {
                    "concept_id": concept_mapping.concept_id,
                    "concept_name": concept_mapping.concept_name,
                    "teaching_type": concept_mapping.teaching_type,
                    "assist2017_concept_id": concept_mapping.assist2017_concept_id,
                    "source": concept_mapping.source_provenance.source,
                }
            )

        coverage_type = "global"
        missing_reason = None
        if document.question_id:
            coverage_type = "question" if question_mapping is not None else "unmapped_question"
            if question_mapping is None:
                missing_reason = "RAG doc question_id is not present in canonical mapping."
        elif document.concept_id:
            coverage_type = "concept" if concept_mapping is not None else "unmapped_concept"
            if concept_mapping is None:
                missing_reason = "RAG doc concept_id is not present in canonical mapping."

        provenance = {
            "rag_source": "data/rag/demo_knowledge.json",
            "source": document.source,
            "mapping_source": canonical_mapping.get("source"),
            "enrichment": "runtime_canonical_mapping",
        } | document.provenance
        coverage = {
            "coverage_type": coverage_type,
            "doc_type": document.doc_type,
            "question_aligned": question_mapping is not None,
            "concept_aligned": (question_mapping is not None or concept_mapping is not None),
            "missing_reason": missing_reason,
        } | document.coverage

        return document.model_copy(
            update={
                "assist2017_question_id": assist_question_id,
                "assist2017_concept_id": assist_concept_id,
                "canonical_mapping": canonical_mapping,
                "provenance": provenance,
                "coverage": coverage,
            }
        )


knowledge_rag = LocalKnowledgeRAG()
