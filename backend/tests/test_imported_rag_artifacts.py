from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.core.config import MathTutorSettings
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.importing.assist2017_artifacts import RAGDocumentArtifact
from backend.app.main import create_app
from backend.app.planning.recommender import RiskPrioritizedRecommender
from backend.app.rag.knowledge_rag import (
    LocalKnowledgeRAG,
    RAGArtifactConfigurationError,
    create_knowledge_rag,
)
from backend.app.rag.schema import RAGSearchResult
from backend.app.storage.content_repository import ImportedTeachingContentRepository
from backend.app.storage.progress_store import InMemoryProgressStore


ROOT = Path(__file__).resolve().parents[2]
IMPORTED_CONTENT = ROOT / "data" / "imported" / "assist2017_fixture" / "content_import.json"
IMPORTED_RAG = ROOT / "data" / "imported" / "assist2017_fixture" / "rag_documents.json"


def test_imported_rag_artifact_contains_four_doc_types_with_canonical_metadata() -> None:
    artifact = RAGDocumentArtifact.model_validate_json(IMPORTED_RAG.read_text(encoding="utf-8"))

    doc_types = {document.doc_type for document in artifact.documents}
    question_doc = next(
        document
        for document in artifact.documents
        if document.doc_id == "rag_assist2017_q000003_question_explanation"
    )

    assert doc_types == {
        "concept_note",
        "question_explanation",
        "mistake_pattern",
        "learning_strategy",
    }
    assert artifact.metadata.row_counts["rag_documents"] == 11
    assert question_doc.question_id == "q_assist2017_000003"
    assert question_doc.concept_id == "c_assist2017_0002"
    assert question_doc.assist2017_question_id == 3
    assert question_doc.assist2017_concept_id == 2
    assert question_doc.canonical_mapping["assist2017_question_id"] == 3
    assert question_doc.coverage["question_aligned"] is True


def test_local_rag_reads_imported_artifact_with_existing_result_contract() -> None:
    rag = LocalKnowledgeRAG(documents_path=IMPORTED_RAG, mapping_path=None)

    results = rag.search(
        query="通分 题解",
        filters={
            "doc_type": "question_explanation",
            "question_id": "q_assist2017_000003",
            "concept_id": "c_assist2017_0002",
        },
        limit=3,
    )

    assert [result.doc_id for result in results] == [
        "rag_assist2017_q000003_question_explanation"
    ]
    assert isinstance(results[0], RAGSearchResult)
    assert results[0].question_id == "q_assist2017_000003"
    assert results[0].concept_id == "c_assist2017_0002"
    assert results[0].assist2017_question_id == 3
    assert results[0].assist2017_concept_id == 2
    assert results[0].coverage["coverage_type"] == "question"
    assert results[0].coverage["question_aligned"] is True
    assert results[0].provenance["rag_source"] == "assist2017_import_builder"


def test_create_knowledge_rag_requires_explicit_imported_artifact_path() -> None:
    settings = MathTutorSettings(rag_source="imported", rag_artifact_path="")

    try:
        create_knowledge_rag(settings)
    except RAGArtifactConfigurationError as exc:
        assert "MATHTUTOR_RAG_ARTIFACT_PATH" in str(exc)
    else:
        raise AssertionError("expected imported RAG artifact path configuration error")


def test_imported_rag_flows_to_recommendation_trace_and_context(
    monkeypatch,
) -> None:
    repository = ImportedTeachingContentRepository(IMPORTED_CONTENT)
    rag = LocalKnowledgeRAG(documents_path=IMPORTED_RAG, mapping_path=None)
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            store=InMemoryProgressStore(),
            content=repository,
            question_recommender=RiskPrioritizedRecommender(content=repository),
            rag=rag,
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-imported-rag-001",
            "student_id": "student-imported-rag-001",
            "type": "answer_submitted",
            "message": "我故意答错导入题，验证 RAG 对齐",
            "payload": {
                "question_id": "q_assist2017_000003",
                "answer": "1/6",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    rag_sources = expert["rag_sources"]
    knowledge_assets = [
        asset
        for asset in expert["context_assets"]
        if asset["asset_type"] == "knowledge_resource"
    ]
    plan = expert["planner_decision"]

    assert rag_sources
    assert all(source["question_id"] == "q_assist2017_000003" for source in rag_sources)
    assert all(source["concept_id"] == "c_assist2017_0002" for source in rag_sources)
    assert rag_sources[0]["assist2017_question_id"] == 3
    assert rag_sources[0]["assist2017_concept_id"] == 2
    assert rag_sources[0]["coverage"]["question_aligned"] is True
    assert knowledge_assets
    assert knowledge_assets[0]["question_id"] == "q_assist2017_000003"
    assert knowledge_assets[0]["metadata"]["canonical_mapping"]["assist2017_question_id"] == 3
    assert plan["evidence"]["rag_sources"][0]["question_id"] == "q_assist2017_000003"
    assert expert["kt_diagnosis"]["weak_concepts"][0]["concept_id"] == "c_assist2017_0002"
    assert "参考：" in body["response"]


def test_missing_question_rag_doc_reports_gap_without_adjacent_fallback(
    monkeypatch,
) -> None:
    repository = ImportedTeachingContentRepository(IMPORTED_CONTENT)
    fallback_rag = QuestionStrictFallbackDetectingRAG()
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            store=InMemoryProgressStore(),
            content=repository,
            question_recommender=RiskPrioritizedRecommender(content=repository),
            rag=fallback_rag,
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-imported-rag-gap-001",
            "student_id": "student-imported-rag-gap-001",
            "type": "answer_submitted",
            "message": "验证缺失 RAG 不使用相邻 fallback",
            "payload": {
                "question_id": "q_assist2017_000003",
                "answer": "1/6",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    gaps = expert["assembled_context"]["evidence_gaps"]

    assert fallback_rag.calls == [
        {
            "doc_types": ["question_explanation", "mistake_pattern", "learning_strategy"],
            "question_id": "q_assist2017_000003",
            "concept_id": "c_assist2017_0002",
        }
    ]
    assert expert["rag_sources"] == []
    assert any(gap["gap_type"] == "missing_rag_citation" for gap in gaps)
    assert expert["kt_diagnosis"]["weak_concepts"][0]["concept_id"] == "c_assist2017_0002"


class QuestionStrictFallbackDetectingRAG:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> list[RAGSearchResult]:
        filters = filters or {}
        self.calls.append(dict(filters))
        if filters.get("question_id"):
            return []
        return [
            RAGSearchResult(
                doc_id="rag_adjacent_should_not_be_used",
                doc_type="concept_note",
                title="不应使用的相邻文档",
                content="这个文档只有概念相近，不是当前题证据。",
                source="test-only",
                concept_id="c_assist2017_0002",
                question_id=None,
                assist2017_concept_id=2,
                score=1.0,
            )
        ]

