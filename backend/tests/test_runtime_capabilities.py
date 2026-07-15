from fastapi.testclient import TestClient

from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.main import create_app
from backend.app.runtime import (
    MathCapabilityRegistry,
    MathTutorAgentRuntime,
    default_capability_registry,
)
from backend.app.schemas.learning import LearningEvent
from backend.app.storage.progress_store import InMemoryProgressStore


def test_default_capability_registry_lists_math_only_capability_manifest() -> None:
    manifest = default_capability_registry.manifest()
    by_id = {item["capability_id"]: item for item in manifest}

    assert set(by_id) == {
        "math_answer_diagnosis",
        "math_next_step_advice",
        "math_concept_explanation",
    }
    assert by_id["math_answer_diagnosis"]["applicable_intents"] == ["answer_submission"]
    assert "kt_state_engine" in by_id["math_answer_diagnosis"]["expected_tools"]
    assert "question_recommender" in by_id["math_next_step_advice"]["expected_tools"]
    assert "rag_retrieval" in by_id["math_concept_explanation"]["expected_tools"]
    assert all(
        item["state_write_policy"] == "capability_never_writes_learning_facts_directly"
        for item in manifest
    )


def test_runtime_selects_math_capability_and_records_trace_summary() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-capability-001",
            "student_id": "student-capability-001",
            "type": "answer_submitted",
            "message": "答案是 1/6",
            "payload": {
                "question_id": "q_frac_001",
                "answer": "1/6",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    active_capability = expert["active_capability"]
    runtime_start = next(
        event for event in body["teaching_trace"] if event["stage"] == "runtime_start"
    )

    assert active_capability["capability_id"] == "math_answer_diagnosis"
    assert active_capability["selected"] is True
    assert active_capability["fallback"] is False
    assert "intent=answer_submission" in active_capability["reason"]
    assert "kt_state_engine" in active_capability["expected_tools"]
    assert "dgekt_attribution" in active_capability["expected_tools"]
    assert active_capability["delegated_to"] == "MathTutorLearningLoop"
    assert active_capability["state_write_policy"].startswith("selection_is_read_only")
    assert expert["runtime"]["active_capability_id"] == "math_answer_diagnosis"
    assert expert["capability_manifest"][0]["capability_id"] == "math_answer_diagnosis"
    assert "答题诊断与错因分析" in runtime_start["content"]
    assert runtime_start["metadata"]["capability_selection"] == active_capability
    assert "capability:math_answer_diagnosis" in runtime_start["evidence_refs"]
    assert expert["kt_diagnosis"]["prediction_probability"] == 0.58


def test_runtime_capability_fallback_keeps_default_learning_flow_running() -> None:
    runtime = MathTutorAgentRuntime(
        learning_loop=MathTutorLearningLoop(store=InMemoryProgressStore()),
        capability_registry=MathCapabilityRegistry(capabilities=[]),
    )

    response = runtime.handle_event(
        LearningEvent(
            session_id="session-capability-fallback-001",
            student_id="student-capability-fallback-001",
            type="chat_message",
            message="推荐下一题",
            payload={},
        )
    )

    expert = response.teaching_trace_summary.expert_evidence
    active_capability = expert["active_capability"]
    runtime_start = next(
        event for event in response.teaching_trace if event.stage == "runtime_start"
    )

    assert response.state_summary["intent"] == "next_step_advice"
    assert response.recommended_questions
    assert active_capability["capability_id"] == "fallback_existing_learning_loop"
    assert active_capability["selected"] is False
    assert active_capability["fallback"] is True
    assert active_capability["expected_tools"] == []
    assert "没有匹配 intent=next_step_advice" in active_capability["reason"]
    assert "fallback" in runtime_start.content
    assert "capability:fallback_existing_learning_loop" in runtime_start.evidence_refs
