from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol

from ..core.config import MathTutorSettings, get_settings
from ..importing.assist2017_artifacts import RAGDocumentArtifact
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


class RAGArtifactConfigurationError(RuntimeError):
    pass


class RAGProviderConfigurationError(RuntimeError):
    pass


class LocalKnowledgeRAG:
    def __init__(
        self,
        documents_path: str | Path = RAG_PATH,
        mapping_path: str | Path | None = DEFAULT_MAPPING_PATH,
        allows_question_to_concept_fallback: bool | None = None,
    ) -> None:
        self.documents_path = Path(documents_path)
        self.mapping_path = Path(mapping_path) if mapping_path is not None else None
        self.allows_question_to_concept_fallback = (
            self.mapping_path is not None
            if allows_question_to_concept_fallback is None
            else allows_question_to_concept_fallback
        )

    @cached_property
    def documents(self) -> list[RAGDocument]:
        raw_documents = self._load_raw_documents()
        return [
            self._with_canonical_metadata(RAGDocument.model_validate(document))
            for document in raw_documents
        ]

    @cached_property
    def canonical_mapping(self) -> CanonicalMappingRepository | None:
        if self.mapping_path is None:
            return None
        path = _resolve_project_path(self.mapping_path)
        if not path.is_file():
            return None
        return CanonicalMappingRepository.from_path(path)

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
        has_embedded_alignment = bool(
            document.assist2017_question_id
            or document.assist2017_concept_id
            or canonical_mapping.get("assist2017_question_id")
            or canonical_mapping.get("assist2017_concept_id")
            or document.coverage.get("question_aligned")
            or document.coverage.get("concept_aligned")
        )
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
            if question_mapping is None and has_embedded_alignment:
                coverage_type = str(document.coverage.get("coverage_type") or "question")
            elif question_mapping is None:
                missing_reason = "RAG doc question_id is not present in canonical mapping."
        elif document.concept_id:
            coverage_type = "concept" if concept_mapping is not None else "unmapped_concept"
            if concept_mapping is None and has_embedded_alignment:
                coverage_type = str(document.coverage.get("coverage_type") or "concept")
            elif concept_mapping is None:
                missing_reason = "RAG doc concept_id is not present in canonical mapping."

        provenance = {
            "rag_source": _display_path(_resolve_project_path(self.documents_path)),
            "source": document.source,
            "mapping_source": canonical_mapping.get("source"),
            "enrichment": "runtime_canonical_mapping",
        } | document.provenance
        coverage = {
            "coverage_type": coverage_type,
            "doc_type": document.doc_type,
            "question_aligned": (
                question_mapping is not None
                or bool(document.coverage.get("question_aligned"))
            ),
            "concept_aligned": (
                question_mapping is not None
                or concept_mapping is not None
                or bool(document.coverage.get("concept_aligned"))
            ),
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

    def _load_raw_documents(self) -> list[dict[str, Any]]:
        path = _resolve_project_path(self.documents_path)
        if not path.is_file():
            raise RAGArtifactConfigurationError(
                "RAG artifact not found. If MATHTUTOR_RAG_SOURCE=imported, set "
                f"MATHTUTOR_RAG_ARTIFACT_PATH to a valid rag_documents.json; got {self.documents_path}."
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            artifact = RAGDocumentArtifact.model_validate(raw)
            return [document.model_dump() for document in artifact.documents]
        raise ValueError(f"Expected RAG JSON array or artifact object at {path}.")


def create_knowledge_rag(settings: MathTutorSettings | None = None) -> KnowledgeRAG:
    active_settings = settings or get_settings()
    if active_settings.rag_provider_mode == "fake_provider":
        from .fake_provider import FakeKnowledgeRAGProvider

        return FakeKnowledgeRAGProvider()
    if active_settings.rag_provider_mode == "live_provider":
        from .viking_provider import create_viking_knowledge_rag_adapter

        return create_viking_knowledge_rag_adapter(
            active_settings,
            fallback=_create_local_fallback_or_none(active_settings),
        )
    return _create_local_knowledge_rag(active_settings)


def _create_local_fallback_or_none(active_settings: MathTutorSettings) -> KnowledgeRAG | None:
    try:
        return _create_local_knowledge_rag(active_settings)
    except RAGArtifactConfigurationError:
        return None


def _create_local_knowledge_rag(active_settings: MathTutorSettings) -> KnowledgeRAG:
    if active_settings.rag_source == "demo":
        return LocalKnowledgeRAG()
    if active_settings.rag_source == "imported":
        if not active_settings.rag_artifact_path:
            raise RAGArtifactConfigurationError(
                "MATHTUTOR_RAG_SOURCE=imported 时必须设置 "
                "MATHTUTOR_RAG_ARTIFACT_PATH 指向 rag_documents.json。"
            )
        return LocalKnowledgeRAG(
            documents_path=active_settings.rag_artifact_path,
            mapping_path=None,
            allows_question_to_concept_fallback=False,
        )
    raise RAGArtifactConfigurationError(f"Unsupported RAG source: {active_settings.rag_source}")


def _display_path(path: Path) -> str:
    project_root = Path(__file__).resolve().parents[3]
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def _resolve_project_path(path: str | Path) -> Path:
    resolved = Path(path)
    if resolved.is_absolute() or resolved.exists():
        return resolved
    return Path(__file__).resolve().parents[3] / resolved


knowledge_rag = create_knowledge_rag()
