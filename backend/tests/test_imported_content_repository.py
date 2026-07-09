from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.core.config import MathTutorSettings
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.main import create_app
from backend.app.planning.recommender import RiskPrioritizedRecommender
from backend.app.rag.knowledge_rag import LocalKnowledgeRAG
from backend.app.schemas.learning import KTDiagnosis, KTLearningProgress
from backend.app.storage.content_repository import (
    ContentArtifactConfigurationError,
    ImportedTeachingContentRepository,
    create_content_repository,
)
from backend.app.storage.progress_store import InMemoryProgressStore


ROOT = Path(__file__).resolve().parents[2]
IMPORTED_CONTENT = ROOT / "data" / "imported" / "assist2017_fixture" / "content_import.json"
IMPORTED_RAG = ROOT / "data" / "imported" / "assist2017_fixture" / "rag_documents.json"


def test_imported_repository_loads_canonical_content_artifact() -> None:
    repository = ImportedTeachingContentRepository(IMPORTED_CONTENT)

    questions = repository.list_questions()
    public = repository.public_question(questions[0])

    assert questions[0]["question_id"] == "q_assist2017_000001"
    assert questions[0]["stem"] == "快速回答：7 × 8 = ?"
    assert questions[0]["standard_answer"] == "56"
    assert questions[0]["explanation"] == "7 × 8 是常用乘法事实，结果是 56。"
    assert questions[0]["concept_id"] == "c_assist2017_0001"
    assert questions[0]["concept_ids"] == ["c_assist2017_0001"]
    assert questions[0]["assist2017_question_id"] == 1
    assert questions[0]["assist2017_concept_id"] == 1
    assert questions[0]["difficulty"] == 0.2
    assert questions[0]["mistake_patterns"] == ["乘法事实记忆不稳", "相邻口诀混淆"]
    assert questions[0]["content_availability"]["status"] == "available"
    assert public["answer"] == "56"
    assert public["provenance"]["content_source"].endswith(
        "data/imported/assist2017_fixture/content_import.json"
    )
    assert public["provenance"]["source_row_id"] == "assist2017-fixture-row-1"
    assert public["canonical_mapping"]["assist2017_question_id"] == 1
    assert public["canonical_mapping"]["assist2017_concept_id"] == 1


def test_imported_repository_surfaces_partial_content_without_fabrication() -> None:
    repository = ImportedTeachingContentRepository(IMPORTED_CONTENT)

    partial = repository.get_question("q_assist2017_000005")
    assert partial is not None
    public = repository.public_question(partial)

    assert public["stem"] == "解方程：x + 5 = 12。"
    assert public["answer"] == "7"
    assert public["explanation"] is None
    assert public["content_availability"]["status"] == "partial"
    assert public["content_availability"]["missing_fields"] == ["explanation"]
    assert public["content_availability"]["fallback_message"].startswith(
        "q_assist2017_000005 缺少解析"
    )


def test_create_content_repository_requires_explicit_import_path() -> None:
    settings = MathTutorSettings(content_source="imported", content_import_path="")

    try:
        create_content_repository(settings)
    except ContentArtifactConfigurationError as exc:
        assert "MATHTUTOR_CONTENT_IMPORT_PATH" in str(exc)
    else:
        raise AssertionError("expected imported content path configuration error")


def test_recommender_prefers_complete_imported_content_when_candidates_are_close(
    tmp_path: Path,
) -> None:
    raw = json.loads(IMPORTED_CONTENT.read_text(encoding="utf-8"))
    complete = dict(raw["questions"][0])
    partial = json.loads(json.dumps(complete))
    partial["question_id"] = "q_assist2017_000099"
    partial["assist2017_question_id"] = 99
    partial["stem"] = None
    partial["explanation"] = None
    partial["content_availability"] = {
        "status": "partial",
        "has_stem": False,
        "has_answer": True,
        "has_explanation": False,
        "has_concept_metadata": True,
        "missing_fields": ["stem", "explanation"],
        "missing_reason_codes": ["missing_stem", "missing_explanation"],
        "fallback_message": "q_assist2017_000099 缺少题干、解析。",
    }
    raw["questions"] = [partial, complete]
    artifact_path = tmp_path / "content_import.json"
    artifact_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    repository = ImportedTeachingContentRepository(artifact_path)

    recommendations = RiskPrioritizedRecommender(content=repository).recommend(
        progress=KTLearningProgress(student_id="student-imported-ranking"),
        diagnosis=KTDiagnosis(),
        limit=2,
    )

    assert recommendations[0]["question_id"] == "q_assist2017_000001"
    assert recommendations[0]["score_factors"]["content_completeness"] == 1.0
    assert recommendations[1]["question_id"] == "q_assist2017_000099"
    assert recommendations[1]["content_availability"]["status"] == "partial"


def test_imported_content_api_grades_and_traces_canonical_question(
    monkeypatch,
) -> None:
    repository = ImportedTeachingContentRepository(IMPORTED_CONTENT)
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            store=InMemoryProgressStore(),
            content=repository,
            question_recommender=RiskPrioritizedRecommender(content=repository),
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-imported-content-001",
            "student_id": "student-imported-content-001",
            "type": "answer_submitted",
            "message": "我故意答错 fixture 导入题",
            "payload": {
                "question_id": "q_assist2017_000003",
                "answer": "1/6",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    load_trace = body["teaching_trace"][0]
    expert = body["teaching_trace_summary"]["expert_evidence"]
    first_recommendation = body["recommended_questions"][0]

    assert body["state_summary"]["intent"] == "answer_submission"
    assert body["state_summary"]["mistake_diagnosis"]["concept"]["concept_id"] == (
        "c_assist2017_0002"
    )
    assert load_trace["metadata"]["grading_source"] == "assist2017_content_import"
    assert load_trace["metadata"]["is_correct"] is False
    assert first_recommendation["concept_id"] == "c_assist2017_0002"
    assert first_recommendation["assist2017_question_id"] == 3
    assert first_recommendation["canonical_mapping"]["assist2017_question_id"] == 3
    assert first_recommendation["provenance"]["content_source"].endswith(
        "data/imported/assist2017_fixture/content_import.json"
    )
    assert any(
        recommendation["canonical_mapping"]["assist2017_question_id"] == 3
        for recommendation in expert["recommendations"]
    )
    assert expert["kt_diagnosis"]["weak_concepts"][0]["concept_id"] == "c_assist2017_0002"


def test_imported_partial_content_gap_is_visible_in_trace_without_fabrication(
    monkeypatch,
) -> None:
    repository = ImportedTeachingContentRepository(IMPORTED_CONTENT)
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            store=InMemoryProgressStore(),
            content=repository,
            question_recommender=RiskPrioritizedRecommender(content=repository),
            rag=LocalKnowledgeRAG(documents_path=IMPORTED_RAG, mapping_path=None),
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-imported-content-gap-001",
            "student_id": "student-imported-content-gap-001",
            "type": "answer_submitted",
            "message": "提交一题内容不完整但可判题的 fixture 题",
            "payload": {
                "question_id": "q_assist2017_000005",
                "answer": "7",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    load_trace = body["teaching_trace"][0]
    expert = body["teaching_trace_summary"]["expert_evidence"]
    content_gap = next(
        record
        for record in expert["error_records"]
        if record["code"] == "partial_teaching_content"
    )
    evidence_gap = next(
        gap
        for gap in expert["assembled_context"]["evidence_gaps"]
        if gap.get("code") == "partial_teaching_content"
    )

    assert load_trace["metadata"]["target_content"]["canonical_question_id"] == (
        "q_assist2017_000005"
    )
    assert load_trace["metadata"]["target_content"]["canonical_concept_id"] == (
        "c_assist2017_0003"
    )
    assert load_trace["metadata"]["target_content"]["content_availability"]["status"] == (
        "partial"
    )
    assert load_trace["metadata"]["target_content"]["provenance"]["source_row_id"] == (
        "assist2017-fixture-row-5"
    )
    assert content_gap["category"] == "missing_teaching_content"
    assert content_gap["details"]["missing_fields"] == ["explanation"]
    assert content_gap["details"]["canonical_question_id"] == "q_assist2017_000005"
    assert content_gap["details"]["provenance"]["source_row_id"] == "assist2017-fixture-row-5"
    assert evidence_gap["details"]["content_availability"]["missing_reason_codes"] == [
        "missing_explanation"
    ]
    assert body["state_summary"]["errors"] == []
    assert expert["kt_diagnosis"]["weak_concepts"] == []
