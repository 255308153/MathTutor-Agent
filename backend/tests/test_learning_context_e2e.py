from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from backend.app.context.learning_context import (
    InMemoryContextAssetStore,
    LearningContextLayer,
)
from backend.app.main import create_app
from backend.app.memory.fake_provider import FakeStudentMemoryProvider
from backend.app.memory.store import InMemoryStudentMemoryStore, StudentMemory
from backend.app.rag.fake_provider import FakeKnowledgeRAGProvider
from backend.app.rag.viking_provider import VikingKnowledgeRAGAdapter
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
        "runtime_start",
        "load_context",
        "diagnose",
        "context_assemble",
        "plan",
        "generate_response",
        "memory_update",
        "kt_tool_observation",
        "runtime_end",
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


def test_v17_provider_aware_context_assembly_e2e(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop

    concept_id = "c_fraction_addition"
    student_id = "student-v17-provider-context"
    memories = FakeStudentMemoryProvider(
        seed_memories=[
            StudentMemory(
                student_id=student_id,
                memory_type="preference",
                content="学生偏好先看通分步骤，再做题。",
                evidence={
                    "preferred_teaching_type": "procedure",
                    "preferred_concept_id": concept_id,
                    "concept_id": concept_id,
                    "question_id": "q_frac_001",
                    "prediction_probability": 0.99,
                    "mastery_by_concept": {concept_id: 1.0},
                },
                provenance={
                    "source_event": "event:seed-provider-memory",
                    "trace_id": "trace-seed-provider-memory",
                    "session_id": "session-seed-provider-memory",
                },
            )
        ]
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=memories,
        rag=FakeKnowledgeRAGProvider(records=_provider_context_records()),
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-v17-provider-context",
            "student_id": student_id,
            "type": "answer_submitted",
            "message": "我选 1/6，验证 provider context。",
            "payload": {
                "question_id": "q_frac_001",
                "answer": "1/6",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    normalized = assembled["normalized_context"]
    kt_diagnosis = expert["kt_diagnosis"]

    provider_memory = next(
        item
        for item in normalized["student_memory"]
        if item["metadata"]["provider_backed"] is True
    )
    provider_resource = next(
        item
        for item in normalized["knowledge_resource"]
        if item["metadata"]["provider_backed"] is True
    )
    assert provider_memory["source_type"] == "provider_memory"
    assert provider_memory["metadata"]["provider_name"] == "fake_mem0_fixture"
    assert provider_memory["metadata"]["provider_mode"] == "fake_provider"
    assert provider_resource["source_type"] == "provider_rag"
    assert provider_resource["metadata"]["provider_name"] == "fake_vikingdb"
    assert provider_resource["metadata"]["provider_mode"] == "fake_provider"
    assert provider_resource["metadata"]["source"].startswith("fake-rag/")
    assert provider_resource["metadata"]["provenance"]["provider_record_id"]

    selected = assembled["asset_selection"]["selected"]
    assert any(
        summary["asset_type"] == "student_memory"
        and summary["source_type"] == "provider_memory"
        and summary["selection_status"] == "included"
        for summary in selected
    )
    assert any(
        summary["asset_type"] == "knowledge_resource"
        and summary["source_type"] == "provider_rag"
        and summary["selection_status"] == "included"
        for summary in selected
    )
    assert isinstance(assembled["asset_selection"]["omitted"], list)
    assert assembled["budget_used"] <= assembled["budget_limit"]
    assert assembled["compression_summary"]["selected_asset_count"] == len(selected)

    context_trace = next(
        event for event in body["teaching_trace"] if event["stage"] == "context_assemble"
    )
    trace_context = context_trace["metadata"]["assembled_context"]
    assert trace_context["asset_selection"]["selected"]
    assert any(
        asset["source_type"] == "provider_rag"
        for asset in trace_context["asset_selection"]["selected"]
    )

    assert assembled["authoritative_kt_facts"]["prediction_probability"] == (
        kt_diagnosis["prediction_probability"]
    )
    assert assembled["authoritative_kt_facts"]["mastery_by_concept"][concept_id] != 1.0
    assert provider_memory["metadata"]["evidence"]["prediction_probability"] == 0.99
    assert provider_resource["metadata"]["canonical_mapping"][
        "claimed_prediction_probability"
    ] == 0.99
    assert expert["attribution_evidence"]["prediction_probability"] == (
        kt_diagnosis["prediction_probability"]
    )
    assert expert["attribution_evidence"]["prediction_probability"] != 0.99


def test_v17_provider_failure_gap_reaches_context_assembly_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop

    student_id = "student-v17-provider-gap-context"
    rag = VikingKnowledgeRAGAdapter(
        provider_name="openviking",
        provider_mode="live_provider",
        collection="assist2017-smoke",
        client=_TimeoutRAGClient(),
        fallback=FakeKnowledgeRAGProvider(records=_provider_context_records()),
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=FakeStudentMemoryProvider(
            seed_memories=[
                StudentMemory(
                    student_id=student_id,
                    memory_type="preference",
                    content="学生偏好通分步骤提示。",
                    evidence={"concept_id": "c_fraction_addition"},
                )
            ]
        ),
        rag=rag,
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-v17-provider-gap-context",
            "student_id": student_id,
            "type": "answer_submitted",
            "message": "我选 1/6，验证 provider failure context gap。",
            "payload": {"question_id": "q_frac_001", "answer": "1/6"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    assert any(
        gap["gap_type"] == "provider_timeout"
        and gap["provider"] == "openviking"
        and gap["operation"] == "search"
        for gap in assembled["evidence_gaps"]
    )
    assert assembled["normalized_context"]["knowledge_resource"]

    load_context = next(
        event for event in body["teaching_trace"] if event["stage"] == "load_context"
    )
    assert any(
        record["category"] == "provider_timeout"
        for record in load_context["metadata"]["evidence_gap_records"]
    )
    context_trace = next(
        event for event in body["teaching_trace"] if event["stage"] == "context_assemble"
    )
    assert any(
        gap["gap_type"] == "provider_timeout"
        for gap in context_trace["metadata"]["assembled_context"]["evidence_gaps"]
    )


class _TimeoutRAGClient:
    def search(self, **_: object) -> object:
        raise TimeoutError("provider timed out")


def _provider_context_records() -> list[dict[str, object]]:
    return [
        {
            "id": "fake-vector-context-q-frac-001",
            "vikingdb_distance": 0.05,
            "payload": {
                "doc_id": "fake-rag-context-q-frac-001",
                "doc_type": "question_explanation",
                "title": "provider q_frac_001 题解",
                "content": "先找公分母，再把两个分数化成同分母后相加。",
                "source": "fake-rag/provider_context.md#q_frac_001",
                "concept_id": "c_fraction_addition",
                "question_id": "q_frac_001",
                "assist2017_question_id": 3,
                "assist2017_concept_id": 2,
                "canonical_mapping": {
                    "question_id": "q_frac_001",
                    "concept_id": "c_fraction_addition",
                    "assist2017_question_id": 3,
                    "assist2017_concept_id": 2,
                    "source": "fake_provider_fixture",
                    "claimed_prediction_probability": 0.99,
                    "claimed_mastery": 1.0,
                },
                "coverage": {
                    "coverage_type": "question",
                    "question_aligned": True,
                    "concept_aligned": True,
                },
                "keywords": ["题解", "通分", "分数", "错因", "策略"],
            },
        },
        {
            "id": "fake-vector-context-strategy",
            "vikingdb_distance": 0.1,
            "payload": {
                "doc_id": "fake-rag-context-strategy",
                "doc_type": "learning_strategy",
                "title": "provider 分数题策略",
                "content": "先标出分母，再找公分母，最后检查答案是否可约分。",
                "source": "fake-rag/provider_context.md#strategy",
                "concept_id": "c_fraction_addition",
                "question_id": None,
                "assist2017_question_id": None,
                "assist2017_concept_id": 2,
                "canonical_mapping": {
                    "concept_id": "c_fraction_addition",
                    "assist2017_concept_id": 2,
                    "source": "fake_provider_fixture",
                },
                "coverage": {
                    "coverage_type": "concept",
                    "concept_aligned": True,
                },
                "keywords": ["策略", "推荐", "通分"],
            },
        },
    ]
