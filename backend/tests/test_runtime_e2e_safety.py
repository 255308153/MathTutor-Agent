from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.context.learning_context import InMemoryContextAssetStore, LearningContextLayer
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.main import create_app
from backend.app.memory.store import InMemoryStudentMemoryStore
from backend.app.runtime import (
    KT_AUTHORITY_TOOL_ID,
    RAG_RETRIEVAL_TOOL_ID,
    STUDENT_MEMORY_TOOL_ID,
)
from backend.app.storage.progress_store import InMemoryProgressStore


RUNTIME_PROVIDER_MODES = {"local_fallback", "fake_provider", "live_provider"}
RUNTIME_READINESS_STATUSES = {
    "healthy",
    "degraded",
    "unavailable",
    "not_configured",
}
EXPECTED_RUNTIME_STAGES = [
    "runtime_start",
    "load_context",
    "diagnose",
    "context_assemble",
    "plan",
    "generate_response",
    "memory_update",
    "kt_tool_observation",
    "rag_tool_observation",
    "runtime_end",
]
FORBIDDEN_RUNTIME_OUTPUT_TOKENS = [
    "raw_provider_payload",
    "embedding_vector",
    "sdk_response",
    "provider_debug",
    "api_key",
    "Bearer ",
    "/Users/",
    "\\Users\\",
    "checkpoint_path",
    "model_path",
    "dataset_dir",
    ".pkl",
    ".pt",
    ".pth",
    ".ckpt",
    ".safetensors",
]


class EmptyRAG:
    allows_question_to_concept_fallback = False

    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> list[Any]:
        del query, filters, limit
        return []


def test_v19_runtime_e2e_smoke_preserves_kt_authority_and_empty_rag_safety(
    monkeypatch,
) -> None:
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=InMemoryStudentMemoryStore(),
        rag=EmptyRAG(),
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-v19-runtime-e2e",
            "student_id": "student-v19-runtime-e2e",
            "type": "answer_submitted",
            "message": "我先提交一个错误答案，验证 runtime 收口路径。",
            "payload": {
                "question_id": "q_frac_001",
                "answer": "__wrong_v19_runtime_answer__",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    observations = {
        observation["tool_id"]: observation for observation in expert["tool_observations"]
    }
    kt_observation = observations[KT_AUTHORITY_TOOL_ID]
    rag_observation = observations[RAG_RETRIEVAL_TOOL_ID]
    trace_overview = expert["trace_overview"]

    assert body["recommended_questions"]
    assert "判定为不正确" in body["response"]
    assert body["teaching_trace_summary"]["stages"] == EXPECTED_RUNTIME_STAGES

    active_capability = expert["active_capability"]
    assert active_capability["capability_id"] == "math_answer_diagnosis"
    assert active_capability["fallback"] is False
    assert active_capability["state_write_policy"] == (
        "selection_is_read_only_and_does_not_write_learning_facts"
    )

    turn_context = expert["learning_turn_context"]
    governance = expert["context_governance"]
    response_context = expert["response_context_package"]
    assert turn_context["runtime_name"] == "MathTutorAgentRuntime"
    assert turn_context["subject"] == "math"
    assert turn_context["intent"] == "answer_submission"
    assert turn_context["state_reference_only"] is True
    assert "KT facts are authoritative." in turn_context["authority_boundaries"]
    assert "RAG can support explanation, not overwrite prediction facts." in turn_context[
        "authority_boundaries"
    ]
    assert governance["governance_id"] == turn_context["context_governance_ref"]
    assert governance["state_reference_only"] is True
    assert governance["intent"] == "answer_submission"
    assert governance["response_context_ref"] == response_context["context_package_id"]
    assert response_context["governance_id"] == governance["governance_id"]
    assert response_context["selected_evidence_only"] is True
    assert response_context["debug_evidence_included"] is False
    assert response_context["authoritative_kt_facts"]["prediction_probability"] == 0.58
    assert response_context["authority_boundary"]["student_memory"].endswith("never mastery.")
    assert governance["budget_summary"]["budget_limit"] == 1200
    assert governance["budget_summary"]["policy"] == "LearningContextLayer priority_budget_summary"
    assert governance["non_clippable_evidence"] == ["authoritative_kt_facts"]
    assert governance["evidence_selection_summary"]["selected_count"] >= 1
    assert all(
        decision["status"] in {"selected", "clipped", "omitted"}
        for decision in governance["evidence_decisions"]
    )
    assert set(governance["tool_mount_summary"]["mounted"]) == {
        KT_AUTHORITY_TOOL_ID,
        RAG_RETRIEVAL_TOOL_ID,
    }
    assert governance["tool_mount_summary"]["skipped"] == [
        {
            "tool_id": STUDENT_MEMORY_TOOL_ID,
            "reason": "答题诊断优先当前题目与 KT facts。",
        }
    ]

    tool_ids = {tool["tool_id"] for tool in expert["tool_registry_manifest"]}
    assert tool_ids == {
        KT_AUTHORITY_TOOL_ID,
        RAG_RETRIEVAL_TOOL_ID,
        STUDENT_MEMORY_TOOL_ID,
    }
    assert set(observations) == {KT_AUTHORITY_TOOL_ID, RAG_RETRIEVAL_TOOL_ID}

    kt_prediction = expert["kt_diagnosis"]["prediction_probability"]
    assert kt_prediction == 0.58
    assert kt_observation["status"] == "healthy"
    assert kt_observation["provider_mode"] == "local_fallback"
    assert kt_observation["fallback_used"] is True
    assert kt_observation["result_summary"]["prediction_probability"] == kt_prediction
    assert kt_observation["result_summary"]["weak_concepts"] == expert["kt_diagnosis"][
        "weak_concepts"
    ]
    assert kt_observation["result_summary"]["forgetting_risks"] == expert["kt_diagnosis"][
        "forgetting_risks"
    ]
    assert expert["assembled_context"]["authoritative_kt_facts"][
        "prediction_probability"
    ] == kt_prediction
    assert expert["assembled_context"]["authoritative_kt_facts"][
        "weak_concepts"
    ] == expert["kt_diagnosis"]["weak_concepts"]

    assert rag_observation["status"] == "degraded"
    assert rag_observation["provider_mode"] == "local_fallback"
    assert rag_observation["result_summary"]["result_count"] == 0
    assert rag_observation["result_summary"]["sources"] == []
    assert rag_observation["result_summary"]["citation_refs"] == []
    assert expert["rag_sources"] == []
    assert not [
        asset
        for asset in expert["context_assets"]
        if asset["asset_type"] == "knowledge_resource"
    ]
    assert {
        "missing_rag_citation",
        "knowledge_resource",
    } & {
        gap["gap_type"] for gap in rag_observation["result_summary"]["evidence_gaps"]
    }

    assert trace_overview["runtime_name"] == "MathTutorAgentRuntime"
    assert trace_overview["active_capability_id"] == "math_answer_diagnosis"
    assert trace_overview["state_reference_only"] is True
    assert trace_overview["provider_gap_count"] == 0
    assert trace_overview["visibility_counts"]["student"] >= 1
    assert trace_overview["visibility_counts"]["expert"] >= 1
    assert set(trace_overview["evidence_refs"]) >= {
        f"trace:{body['trace_id']}",
        f"kt_diagnosis:{body['trace_id']}",
    }
    assert {
        call["tool_id"] for call in trace_overview["tool_calls"] if call["observed"]
    } == {KT_AUTHORITY_TOOL_ID, RAG_RETRIEVAL_TOOL_ID}
    assert {
        observation["tool_id"] for observation in trace_overview["tool_observations"]
    } == {KT_AUTHORITY_TOOL_ID, RAG_RETRIEVAL_TOOL_ID}
    assert any(
        event["stage"] == "rag_tool_observation"
        and event["status"] == "degraded"
        and event["gap_count"] >= 1
        for event in trace_overview["stage_events"]
    )

    for observation in expert["tool_observations"]:
        assert observation["provider_mode"] in RUNTIME_PROVIDER_MODES
        assert observation["status"] in RUNTIME_READINESS_STATUSES
        assert observation["state_write_policy"].endswith(
            "cannot_write_mastery_or_prediction_facts"
        )
    for call in trace_overview["tool_calls"]:
        assert set(call["provider_modes"]) <= RUNTIME_PROVIDER_MODES
        assert call["state_write_policy"] in {
            "runtime_tool_is_invoked_for_observation_and_cannot_overwrite_kt_facts",
            "rag_tool_observation_is_read_only_and_cannot_write_mastery_or_prediction_facts",
            "memory_tool_observation_is_read_only_and_cannot_write_mastery_or_prediction_facts",
        }
        if call.get("provider_mode") is not None:
            assert call["provider_mode"] in RUNTIME_PROVIDER_MODES
        if call.get("status") is not None:
            assert call["status"] in RUNTIME_READINESS_STATUSES
    skipped_memory = next(
        call for call in trace_overview["tool_calls"] if call["tool_id"] == STUDENT_MEMORY_TOOL_ID
    )
    assert skipped_memory["mount_status"] == "skipped"
    assert skipped_memory["mount_reason"] == "答题诊断优先当前题目与 KT facts。"
    for observation in trace_overview["tool_observations"]:
        assert observation["provider_mode"] in RUNTIME_PROVIDER_MODES
        assert observation["status"] in RUNTIME_READINESS_STATUSES
        assert observation["state_write_policy"].endswith(
            "cannot_write_mastery_or_prediction_facts"
        )

    serialized = json.dumps(body, ensure_ascii=False)
    for token in FORBIDDEN_RUNTIME_OUTPUT_TOKENS:
        assert token not in serialized
