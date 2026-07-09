from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.context.learning_context import LearningContextLayer
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.main import create_app
from backend.app.memory.store import InMemoryStudentMemoryStore
from backend.app.planning.recommender import RiskPrioritizedRecommender
from backend.app.rag.knowledge_rag import LocalKnowledgeRAG
from backend.app.storage.content_repository import ImportedTeachingContentRepository
from backend.app.storage.progress_store import InMemoryProgressStore


ROOT = Path(__file__).resolve().parents[2]
IMPORTED_CONTENT = ROOT / "data" / "imported" / "assist2017_fixture" / "content_import.json"
IMPORTED_RAG = ROOT / "data" / "imported" / "assist2017_fixture" / "rag_documents.json"
SMOKE_DATASET = ROOT / "data" / "imported" / "assist2017_fixture" / "smoke_dataset.json"


def test_assist2017_fixture_smoke_recommend_answer_trace_alignment(
    monkeypatch,
) -> None:
    repository, client = _imported_client(monkeypatch)
    smoke = _smoke_path()
    recommend_step, answer_step = smoke["steps"]
    target_question_id = smoke["canonical_question_id"]
    target_concept_id = smoke["canonical_concept_id"]
    target_assist_question_id = smoke["assist2017_question_id"]
    target_assist_concept_id = smoke["assist2017_concept_id"]

    recommendation_response = client.post(
        "/api/events",
        json={
            "session_id": "session-assist2017-smoke-001",
            "student_id": "student-assist2017-smoke-001",
            "type": recommend_step["event_type"],
            "message": recommend_step["message"],
            "payload": recommend_step["payload"],
        },
    )

    assert recommendation_response.status_code == 200
    recommendation = recommendation_response.json()
    recommended_question = recommendation["recommended_questions"][0]
    recommendation_expert = recommendation["teaching_trace_summary"]["expert_evidence"]
    recommendation_context = recommendation_expert["assembled_context"]

    assert recommended_question["question_id"] == target_question_id
    assert recommended_question["concept_id"] == target_concept_id
    assert recommended_question["assist2017_question_id"] == target_assist_question_id
    assert recommended_question["assist2017_concept_id"] == target_assist_concept_id
    assert recommended_question["content_availability"]["status"] == "available"
    assert f"ASSIST2017 question {target_assist_question_id}" in recommended_question["reason"]
    assert "参考：" in recommendation["response"]
    assert any(
        source["concept_id"] == target_concept_id
        for source in recommendation_expert["rag_sources"]
    )
    assert recommendation_context["authoritative_kt_facts"]["prediction_probability"] is None
    assert recommendation_context["context_invariants"]["rag_boundary"] == (
        "RAG can support explanation, not overwrite prediction facts."
    )
    assert recommendation_expert["planner_decision"]["evidence"]["recommended_question_ids"][0] == (
        target_question_id
    )

    standard_answer = repository.get_question(target_question_id)["standard_answer"]
    assert answer_step["payload"]["answer"] != standard_answer
    answer_response = client.post(
        "/api/events",
        json={
            "session_id": "session-assist2017-smoke-001",
            "student_id": "student-assist2017-smoke-001",
            "type": answer_step["event_type"],
            "message": answer_step["message"],
            "payload": answer_step["payload"],
        },
    )

    assert answer_response.status_code == 200
    answer = answer_response.json()
    answer_expert = answer["teaching_trace_summary"]["expert_evidence"]
    answer_context = answer_expert["assembled_context"]
    load_trace = answer["teaching_trace"][0]
    diagnose_trace = next(event for event in answer["teaching_trace"] if event["stage"] == "diagnose")
    plan_trace = next(event for event in answer["teaching_trace"] if event["stage"] == "plan")
    plan = answer_expert["planner_decision"]
    target_content = load_trace["metadata"]["target_content"]
    rag_sources = answer_expert["rag_sources"]
    knowledge_resources = answer_context["normalized_context"]["knowledge_resource"]

    assert "判定为不正确" in answer["response"]
    assert "乘法口诀事实" in answer["response"]
    assert "参考：" in answer["response"]
    assert answer["state_summary"]["progress_version"] == 2
    assert answer["state_summary"]["weak_concepts"][0]["concept_id"] == target_concept_id
    assert target_content["canonical_question_id"] == target_question_id
    assert target_content["canonical_concept_id"] == target_concept_id
    assert target_content["assist2017_question_id"] == target_assist_question_id
    assert target_content["assist2017_concept_id"] == target_assist_concept_id
    assert target_content["content_availability"]["status"] == "available"
    assert target_content["provenance"]["source_row_id"] == "assist2017-fixture-row-1"
    assert load_trace["metadata"]["grading_source"] == "assist2017_content_import"
    assert load_trace["metadata"]["is_correct"] is False

    assert diagnose_trace["metadata"]["kt_engine"] == "mock"
    assert diagnose_trace["metadata"]["prediction_facts"]["prediction_probability"] == 0.58
    assert diagnose_trace["metadata"]["prediction_facts"]["weak_concepts"][0]["concept_id"] == (
        target_concept_id
    )
    assert answer_context["authoritative_kt_facts"]["prediction_probability"] == 0.58
    assert answer_context["authoritative_kt_facts"]["weak_concepts"][0]["concept_id"] == (
        target_concept_id
    )

    assert {source["doc_type"] for source in rag_sources} == {
        "mistake_pattern",
        "question_explanation",
    }
    assert all(source["question_id"] == target_question_id for source in rag_sources)
    assert all(source["concept_id"] == target_concept_id for source in rag_sources)
    assert all(source["coverage"]["question_aligned"] is True for source in rag_sources)
    assert all(
        "prediction_probability" not in source
        and "mastery" not in source
        for source in rag_sources
    )
    assert any(
        resource["question_id"] == target_question_id
        and resource["metadata"]["coverage"]["question_aligned"] is True
        for resource in knowledge_resources
    )
    assert answer_context["context_invariants"] == {
        "kt_boundary": "KT facts are authoritative.",
        "memory_boundary": "Memory can influence strategy, not mastery.",
        "rag_boundary": "RAG can support explanation, not overwrite prediction facts.",
        "context_boundary": "Context can assemble evidence, not decide learning facts.",
    }

    assert plan["mistake_diagnosis"]["question_id"] == target_question_id
    assert plan["mistake_diagnosis"]["concept"]["concept_id"] == target_concept_id
    assert plan["evidence"]["kt_weak_concepts"][0]["concept_id"] == target_concept_id
    assert all(source["question_id"] == target_question_id for source in plan["evidence"]["rag_sources"])
    assert any(
        target["question_id"] == target_question_id
        and target["concept_id"] == target_concept_id
        and target["assist2017_question_id"] == target_assist_question_id
        for target in plan_trace["metadata"]["selected_canonical_targets"]
    )
    assert f"question:{target_question_id}" in plan_trace["evidence_refs"]
    assert "KT facts are authoritative." in answer["teaching_trace_summary"]["invariants"]
    assert "RAG can support explanation, not overwrite prediction facts." in (
        answer["teaching_trace_summary"]["invariants"]
    )
    assert "Context can assemble evidence, not decide learning facts." in (
        answer["teaching_trace_summary"]["invariants"]
    )


def test_assist2017_smoke_surfaces_partial_and_missing_evidence(
    monkeypatch,
) -> None:
    _repository, client = _imported_client(monkeypatch, rag=NoEvidenceRAG())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-assist2017-gap-smoke-001",
            "student_id": "student-assist2017-gap-smoke-001",
            "type": "answer_submitted",
            "message": "提交一题内容不完整且缺少 RAG evidence 的 fixture 题",
            "payload": {
                "question_id": "q_assist2017_000005",
                "answer": "7",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    load_trace = body["teaching_trace"][0]
    target_content = load_trace["metadata"]["target_content"]
    evidence_gaps = expert["assembled_context"]["evidence_gaps"]

    assert body["state_summary"]["errors"] == []
    assert body["state_summary"]["progress_version"] == 1
    assert expert["rag_sources"] == []
    assert expert["assembled_context"]["normalized_context"]["knowledge_resource"] == []
    assert target_content["canonical_question_id"] == "q_assist2017_000005"
    assert target_content["canonical_concept_id"] == "c_assist2017_0003"
    assert target_content["assist2017_question_id"] == 5
    assert target_content["content_availability"]["status"] == "partial"
    assert target_content["content_availability"]["missing_fields"] == ["explanation"]
    assert any(record["code"] == "partial_teaching_content" for record in expert["error_records"])
    assert any(record["code"] == "missing_rag_citation" for record in expert["error_records"])
    assert any(gap.get("code") == "partial_teaching_content" for gap in evidence_gaps)
    assert any(gap.get("code") == "missing_rag_citation" for gap in evidence_gaps)
    assert any(gap["gap_type"] == "knowledge_resource" for gap in evidence_gaps)


def _imported_client(
    monkeypatch,
    *,
    rag: Any | None = None,
) -> tuple[ImportedTeachingContentRepository, TestClient]:
    repository = ImportedTeachingContentRepository(IMPORTED_CONTENT)
    imported_rag = rag or LocalKnowledgeRAG(documents_path=IMPORTED_RAG, mapping_path=None)
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            store=InMemoryProgressStore(),
            content=repository,
            question_recommender=RiskPrioritizedRecommender(content=repository),
            rag=imported_rag,
            memories=InMemoryStudentMemoryStore(),
            context_layer=LearningContextLayer(),
        ),
    )
    return repository, TestClient(create_app())


def _smoke_path() -> dict[str, Any]:
    artifact = json.loads(SMOKE_DATASET.read_text(encoding="utf-8"))
    return artifact["learning_paths"][0]


class NoEvidenceRAG:
    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> list[Any]:
        return []
