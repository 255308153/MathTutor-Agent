from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from backend.app.context.learning_context import (
    InMemoryContextAssetStore,
    LearningContextLayer,
)
from backend.app.main import create_app
from backend.app.memory.store import InMemoryStudentMemoryStore, StudentMemory
from backend.app.storage.progress_store import InMemoryProgressStore


def test_v14_learning_context_layer_end_to_end_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop

    concept_id = "c_fraction_addition"
    session_id = "session-v14-context-e2e"
    student_id = "student-v14-context-e2e"
    progress_store = InMemoryProgressStore()
    context_store = InMemoryContextAssetStore()
    memories = InMemoryStudentMemoryStore()
    memories.write(
        StudentMemory(
            student_id=student_id,
            memory_type="preference",
            content="分数题偏好步骤化讲解。",
            evidence={
                "preferred_teaching_type": "procedure",
                "preferred_concept_id": concept_id,
                "concept_id": concept_id,
                "mastery_by_concept": {concept_id: 1.0},
                "prediction_probability": 0.99,
            },
        )
    )
    loop = MathTutorLearningLoop(
        store=progress_store,
        memories=memories,
        context_layer=LearningContextLayer(store=context_store),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    first_turn = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {},
        },
    )

    assert first_turn.status_code == 200
    first_body = first_turn.json()
    first_question = first_body["recommended_questions"][0]
    first_expert = first_body["teaching_trace_summary"]["expert_evidence"]
    assert first_question["concept_id"] == concept_id
    assert "参考学生偏好" in first_question["reason"]
    assert "参考相关知识资源" in first_question["reason"]
    assert "context_assemble" in first_body["teaching_trace_summary"]["stages"]
    assert first_expert["assembled_context"]["normalized_context"]["student_memory"]
    assert first_expert["assembled_context"]["normalized_context"]["knowledge_resource"]

    wrong_turn = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "answer_submitted",
            "message": "我故意提交错误答案，验证端到端上下文证据。",
            "payload": {
                "question_id": first_question["question_id"],
                "answer": "__wrong_demo_answer__",
            },
        },
    )

    assert wrong_turn.status_code == 200
    body = wrong_turn.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    normalized = assembled["normalized_context"]
    kt_diagnosis = expert["kt_diagnosis"]
    plan_metadata = next(
        event["metadata"] for event in body["teaching_trace"] if event["stage"] == "plan"
    )

    assert "判定为不正确" in body["response"]
    assert [event["stage"] for event in body["teaching_trace"]] == [
        "load_context",
        "diagnose",
        "context_assemble",
        "plan",
        "generate_response",
        "memory_update",
    ]
    assert any(item["concept_id"] == concept_id for item in kt_diagnosis["weak_concepts"])
    assert any(item["concept_id"] == concept_id for item in kt_diagnosis["forgetting_risks"])
    assert any(
        item["concept_id"] == concept_id
        for item in normalized["student_memory"]
    )
    assert any(
        item["concept_id"] == concept_id
        for item in normalized["knowledge_resource"]
    )
    assert any(
        question["concept_id"] == concept_id
        and "参考学生偏好" in question["reason"]
        and "参考相关知识资源" in question["reason"]
        for question in body["recommended_questions"]
    )
    assert any(
        target["concept_id"] == concept_id
        for target in plan_metadata["selected_canonical_targets"]
    )

    assert assembled["authoritative_kt_facts"]["weak_concepts"] == kt_diagnosis[
        "weak_concepts"
    ]
    assert assembled["authoritative_kt_facts"]["forgetting_risks"] == kt_diagnosis[
        "forgetting_risks"
    ]
    assert (
        assembled["authoritative_kt_facts"]["prediction_probability"]
        == kt_diagnosis["prediction_probability"]
        == 0.58
    )
    assert assembled["authoritative_kt_facts"]["mastery_by_concept"][concept_id] != 1.0
    assert body["state_summary"]["weak_concepts"] == kt_diagnosis["weak_concepts"]
    assert body["state_summary"]["forgetting_risks"] == kt_diagnosis["forgetting_risks"]
    assert normalized["student_memory"][0]["metadata"]["evidence"][
        "prediction_probability"
    ] == 0.99

    selected_context = expert["context_asset_selection"]["selected"]
    assert any(
        asset["asset_type"] == "task_state"
        and asset["source_type"] == "learning_loop_event"
        for asset in selected_context
    )
    assert {
        asset["source_type"]
        for asset in selected_context
        if asset["asset_type"] == "tool_observation"
    }.issuperset({"kt", "rag", "mistake_diagnoser", "recommender"})
    assert any(
        asset["asset_type"] == "trace_reference"
        and asset["source_ref"].endswith(":answer_submission")
        for asset in selected_context
    )
    assert plan_metadata["answer_submission_context_assets"]
    assert expert["context_assets"]
    assert assembled["asset_summaries"]
    assert assembled["budget_used"] <= assembled["budget_limit"]

    kt_asset = next(
        asset
        for asset in expert["context_assets"]
        if asset["asset_type"] == "tool_observation" and asset["source_type"] == "kt"
    )
    assert kt_asset["metadata"]["authoritative_snapshot"] is True
    assert kt_asset["metadata"]["prediction_probability"] == kt_diagnosis[
        "prediction_probability"
    ]
    task_asset = next(
        asset
        for asset in expert["context_assets"]
        if asset["asset_type"] == "task_state"
        and asset["source_type"] == "learning_loop_event"
    )
    assert task_asset["metadata"]["state_reference_only"] is True
    assert task_asset["metadata"]["grading_result"]["is_correct"] is False
    trace_asset = next(
        asset
        for asset in expert["context_assets"]
        if asset["asset_type"] == "trace_reference"
        and asset["source_ref"].endswith(":answer_submission")
    )
    assert trace_asset["metadata"]["memory_update_source"] == (
        f"event:{body['trace_id']}:answer_submitted"
    )

    progress = progress_store.get_or_create(student_id)
    records = context_store.list_assembly_records(
        student_id=student_id,
        session_id=session_id,
    )
    assert progress.version == body["state_summary"]["progress_version"]
    assert progress.concept_states[0].concept_id == concept_id
    assert len(records) >= 2
    assert records[0].context_id == assembled["context_id"]
    assert set(records[0].model_dump()) == {
        "record_id",
        "session_id",
        "student_id",
        "context_id",
        "asset_ids",
        "summary",
        "created_at",
    }
