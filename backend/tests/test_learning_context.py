from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from backend.app.context.learning_context import (
    AssembledContext,
    ContextAsset,
    InMemoryContextAssetStore,
    LearningContextLayer,
)
from backend.app.main import create_app
from backend.app.memory.store import InMemoryStudentMemoryStore, StudentMemory
from backend.app.rag.schema import RAGSearchResult


class EmptyRAG:
    def search(
        self,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 3,
    ) -> list[RAGSearchResult]:
        return []


def test_context_asset_schema_supports_five_asset_types() -> None:
    asset_types = [
        "student_memory",
        "knowledge_resource",
        "task_state",
        "tool_observation",
        "trace_reference",
    ]

    for asset_type in asset_types:
        asset = ContextAsset(
            asset_type=asset_type,
            source_type="test",
            source_ref=f"test:{asset_type}",
            summary=f"{asset_type} summary",
            student_id="student-context-schema",
            session_id="session-context-schema",
            confidence=0.9,
            freshness="fresh",
            included_reason="schema coverage",
        )
        assert asset.asset_id.startswith("ctx-")
        assert asset.asset_type == asset_type

    with pytest.raises(ValidationError):
        ContextAsset(
            asset_type="mastery_fact",
            source_type="test",
            source_ref="test:bad",
            summary="bad",
            confidence=1.4,
        )


def test_context_asset_store_filters_and_orders_assets() -> None:
    store = InMemoryContextAssetStore()
    old = store.write(
        ContextAsset(
            asset_id="ctx-old",
            asset_type="knowledge_resource",
            source_type="rag",
            source_ref="rag:old",
            summary="older fraction note",
            student_id="student-store",
            session_id="session-store",
            concept_id="c_fraction_addition",
            confidence=0.7,
            freshness="recent",
        )
    )
    fresh = store.write(
        ContextAsset(
            asset_id="ctx-fresh",
            asset_type="student_memory",
            source_type="memory",
            source_ref="mem:fresh",
            summary="student prefers worked examples",
            student_id="student-store",
            session_id="session-store",
            concept_id="c_fraction_addition",
            question_id="q_frac_001",
            confidence=0.95,
            freshness="fresh",
        )
    )
    store.write(
        ContextAsset(
            asset_id="ctx-other",
            asset_type="task_state",
            source_type="progress",
            source_ref="progress:other",
            summary="other student state",
            student_id="student-other",
            confidence=1.0,
        )
    )

    results = store.search(
        student_id="student-store",
        asset_types=["student_memory", "knowledge_resource"],
        concept_id="c_fraction_addition",
    )

    assert [asset.asset_id for asset in results] == [fresh.asset_id, old.asset_id]
    assert store.search(student_id="student-store", question_id="q_frac_001")[0].asset_id == "ctx-fresh"


def test_learning_context_layer_assembles_context_without_overwriting_kt_facts() -> None:
    layer = LearningContextLayer(store=InMemoryContextAssetStore())
    kt_facts = {
        "weak_concepts": [{"concept_id": "c_fraction_addition", "mastery": 0.42}],
        "forgetting_risks": [{"concept_id": "c_fraction_addition", "forgetting_risk": 0.6}],
        "prediction_probability": 0.58,
        "mastery_by_concept": {"c_fraction_addition": 0.42},
    }
    assets = [
        ContextAsset(
            asset_id="ctx-memory",
            asset_type="student_memory",
            source_type="memory",
            source_ref="mem:1",
            summary="Student likes visual hints.",
            student_id="student-assemble",
            confidence=0.9,
            metadata={
                "weak_concepts": [{"concept_id": "fake", "mastery": 1.0}],
                "prediction_probability": 0.99,
            },
        )
    ]

    assembled = layer.assemble_context(
        intent="next_step_advice",
        assets=assets,
        kt_facts=kt_facts,
        token_budget=256,
    )

    assert isinstance(assembled, AssembledContext)
    assert assembled.authoritative_kt_facts == kt_facts
    assert assembled.context_invariants["context_boundary"] == (
        "Context can assemble evidence, not decide learning facts."
    )
    assert assembled.asset_summaries[0]["summary"] == "Student likes visual hints."
    assert assembled.normalized_context["student_memory"][0]["kind"] == "student_memory"
    assert assembled.evidence_gaps[0]["reason"] == "RAG 未找到相关知识资源"


def test_learning_context_layer_normalizes_memory_rag_and_evidence_gaps() -> None:
    layer = LearningContextLayer(store=InMemoryContextAssetStore())
    kt_facts = {
        "weak_concepts": [],
        "forgetting_risks": [],
        "prediction_probability": 0.58,
        "mastery_by_concept": {"c_fraction_addition": 0.4},
    }
    assets = [
        ContextAsset(
            asset_type="student_memory",
            source_type="student_memory_store",
            source_ref="memory:pref",
            summary="学生偏好步骤化讲解。",
            metadata={
                "memory_type": "preference",
                "normalized_kind": "preference",
                "evidence": {"preferred_teaching_type": "procedure"},
            },
            included_reason="参考学生偏好",
        ),
        ContextAsset(
            asset_type="knowledge_resource",
            source_type="local_rag",
            source_ref="rag:strategy",
            summary="下一步练习策略：薄弱优先，难度适中",
            metadata={
                "doc_type": "learning_strategy",
                "normalized_kind": "learning_strategy",
                "source": "demo-rag/learning_strategies.md#next-step",
            },
            included_reason="参考学习策略资源",
        ),
    ]

    assembled = layer.assemble_context(
        intent="next_step_advice",
        assets=assets,
        kt_facts=kt_facts,
    )

    normalized = assembled.normalized_context
    assert normalized["strategy_hints"]["preferred_teaching_type"] == "procedure"
    assert normalized["student_memory"][0]["included_reason"] == "参考学生偏好"
    assert normalized["knowledge_resource"][0]["kind"] == "learning_strategy"
    assert normalized["knowledge_hints"]["resource_count"] == 1
    assert assembled.evidence_gaps == []

    no_knowledge = layer.assemble_context(
        intent="next_step_advice",
        assets=assets[:1],
        kt_facts=kt_facts,
    )
    assert no_knowledge.evidence_gaps == [
        {
            "gap_type": "knowledge_resource",
            "reason": "RAG 未找到相关知识资源",
            "impact": "no knowledge_resource asset was fabricated",
        }
    ]


def test_next_step_api_generates_assembled_context_and_preserves_kt_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    memories = InMemoryStudentMemoryStore()
    memories.write(
        StudentMemory(
            student_id="student-context-api",
            memory_type="preference",
            content="学生偏好步骤化讲解。",
            evidence={"preferred_teaching_type": "procedure"},
        )
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=memories,
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-api",
            "student_id": "student-context-api",
            "type": "chat_message",
            "message": "我下一步应该学什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    kt_diagnosis = expert["kt_diagnosis"]

    assert "context_assemble" in body["teaching_trace_summary"]["stages"]
    assert expert["context_assets"]
    assert assembled["authoritative_kt_facts"]["weak_concepts"] == kt_diagnosis["weak_concepts"]
    assert assembled["authoritative_kt_facts"]["forgetting_risks"] == kt_diagnosis["forgetting_risks"]
    assert (
        assembled["authoritative_kt_facts"]["prediction_probability"]
        == kt_diagnosis["prediction_probability"]
    )
    assert body["state_summary"]["weak_concepts"] == kt_diagnosis["weak_concepts"]
    assert body["state_summary"]["forgetting_risks"] == kt_diagnosis["forgetting_risks"]
    assert "Context can assemble evidence, not decide learning facts." in body[
        "teaching_trace_summary"
    ]["invariants"]


def test_next_step_api_consumes_student_memory_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    memories = InMemoryStudentMemoryStore()
    memories.write(
        StudentMemory(
            student_id="student-context-memory",
            memory_type="preference",
            content="学生偏好步骤化讲解，并希望先练比例题。",
            evidence={
                "preferred_teaching_type": "procedure",
                "preferred_concept_id": "c_ratio",
            },
        )
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=memories,
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-memory",
            "student_id": "student-context-memory",
            "type": "chat_message",
            "message": "推荐下一题",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    normalized = assembled["normalized_context"]

    assert normalized["strategy_hints"]["preferred_concept_id"] == "c_ratio"
    assert normalized["student_memory"][0]["included_reason"] == "参考学生偏好"
    assert "参考学生偏好" in body["recommended_questions"][0]["reason"]
    assert "参考学生偏好" in expert["planner_decision"]["evidence"]["context_included_reasons"]
    assert body["recommended_questions"][0]["concept_id"] == "c_ratio"


def test_next_step_api_consumes_knowledge_resource_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=InMemoryStudentMemoryStore(),
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-rag",
            "student_id": "student-context-rag",
            "type": "chat_message",
            "message": "下一步应该学什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    knowledge = assembled["normalized_context"]["knowledge_resource"]

    assert knowledge
    assert {asset["kind"] for asset in knowledge} & {"concept_note", "learning_strategy"}
    assert "参考相关知识资源" in body["recommended_questions"][0]["reason"] or (
        "参考学习策略资源" in body["recommended_questions"][0]["reason"]
    )
    assert not [
        gap for gap in assembled["evidence_gaps"] if gap["gap_type"] == "knowledge_resource"
    ]


def test_next_step_api_marks_memory_gap_for_new_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=InMemoryStudentMemoryStore(),
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-no-memory",
            "student_id": "student-context-no-memory",
            "type": "chat_message",
            "message": "推荐下一题",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assembled = body["teaching_trace_summary"]["expert_evidence"]["assembled_context"]
    context_assets = body["teaching_trace_summary"]["expert_evidence"]["context_assets"]

    assert body["recommended_questions"]
    assert not [asset for asset in context_assets if asset["asset_type"] == "student_memory"]
    assert {
        "gap_type": "student_memory",
        "reason": "无可用记忆",
        "impact": "recommendation uses KT facts and content only",
    } in assembled["evidence_gaps"]
    assert "无可用记忆" in body["recommended_questions"][0]["reason"]


def test_next_step_api_marks_rag_gap_without_fabricating_knowledge_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    memories = InMemoryStudentMemoryStore()
    memories.write(
        StudentMemory(
            student_id="student-context-no-rag",
            memory_type="effective_strategy",
            content="worked example 后再做同类题对学生有效。",
            evidence={"preferred_teaching_type": "procedure"},
        )
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=memories,
        rag=EmptyRAG(),
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-no-rag",
            "student_id": "student-context-no-rag",
            "type": "chat_message",
            "message": "下一步应该学什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    kt_diagnosis = expert["kt_diagnosis"]

    assert body["recommended_questions"]
    assert not [asset for asset in expert["context_assets"] if asset["asset_type"] == "knowledge_resource"]
    assert {
        "gap_type": "knowledge_resource",
        "reason": "RAG 未找到相关知识资源",
        "impact": "no knowledge_resource asset was fabricated",
    } in assembled["evidence_gaps"]
    assert "RAG 未找到相关知识资源" in body["recommended_questions"][0]["reason"]
    assert assembled["authoritative_kt_facts"]["prediction_probability"] == (
        kt_diagnosis["prediction_probability"]
    )


def test_context_assets_cannot_override_mastery_or_prediction_facts() -> None:
    layer = LearningContextLayer(store=InMemoryContextAssetStore())
    kt_facts = {
        "weak_concepts": [{"concept_id": "c_fraction_addition", "mastery": 0.31}],
        "forgetting_risks": [{"concept_id": "c_fraction_addition", "forgetting_risk": 0.72}],
        "prediction_probability": 0.28,
        "mastery_by_concept": {"c_fraction_addition": 0.31},
    }
    assets = [
        ContextAsset(
            asset_type="student_memory",
            source_type="student_memory_store",
            source_ref="memory:malicious",
            summary="伪造学生已经掌握。",
            metadata={
                "normalized_kind": "preference",
                "evidence": {
                    "mastery_by_concept": {"c_fraction_addition": 1.0},
                    "prediction_probability": 0.99,
                },
            },
            included_reason="参考学生偏好",
        ),
        ContextAsset(
            asset_type="knowledge_resource",
            source_type="local_rag",
            source_ref="rag:malicious",
            summary="伪造 RAG 预测事实。",
            metadata={
                "normalized_kind": "concept_note",
                "prediction_probability": 0.95,
                "weak_concepts": [],
            },
            included_reason="参考相关知识资源",
        ),
    ]

    assembled = layer.assemble_context(
        intent="next_step_advice",
        assets=assets,
        kt_facts=kt_facts,
    )

    assert assembled.authoritative_kt_facts == kt_facts
    assert assembled.authoritative_kt_facts["mastery_by_concept"]["c_fraction_addition"] == 0.31
    assert assembled.authoritative_kt_facts["prediction_probability"] == 0.28
    assert assembled.normalized_context["student_memory"][0]["metadata"]["evidence"][
        "prediction_probability"
    ] == 0.99
