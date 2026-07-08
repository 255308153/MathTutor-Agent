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
