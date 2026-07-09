import json
from typing import Any

from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.context.learning_context import InMemoryContextAssetStore, LearningContextLayer
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.kt.dgekt_engine import DGEKTStateEngine
from backend.app.main import create_app
from backend.app.memory.mem0_provider import Mem0StudentMemoryStore
from backend.app.memory.store import InMemoryStudentMemoryStore, StudentMemory
from backend.app.runtime import (
    KT_AUTHORITY_TOOL_ID,
    RAG_RETRIEVAL_TOOL_ID,
    STUDENT_MEMORY_TOOL_ID,
    MathToolRegistry,
    MathTutorAgentRuntime,
    ToolInvocation,
    default_tool_registry,
    kt_authoritative_facts_tool,
)
from backend.app.schemas.learning import LearningEvent
from backend.app.rag.viking_provider import VikingKnowledgeRAGAdapter
from backend.app.storage.progress_store import InMemoryProgressStore
from backend.tests.test_kt_engine_config import (
    patch_fake_dgekt_runtime,
    write_dgekt_fraction_fixture_files,
)


RUNTIME_PROVIDER_MODES = {"local_fallback", "fake_provider", "live_provider"}
RUNTIME_READINESS_STATUSES = {
    "healthy",
    "degraded",
    "unavailable",
    "not_configured",
}


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


class RaisingMem0Client:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def search(self, *_: Any, **__: Any) -> Any:
        raise self.exc

    def get_all(self, *_: Any, **__: Any) -> list[Any]:
        return []

    def add(self, *_: Any, **__: Any) -> Any:
        raise self.exc


class MalformedRAGClient:
    def search(self, **_: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "rag-malformed",
                "metadata": {
                    "doc_type": "question_explanation",
                    "title": "缺少 content 的 provider 记录",
                },
            }
        ]


def test_tool_registry_registers_lists_finds_and_calls_kt_authority_tool() -> None:
    tool = kt_authoritative_facts_tool()
    registry = MathToolRegistry()

    registry.register(tool)
    observation = registry.call(
        KT_AUTHORITY_TOOL_ID,
        ToolInvocation(
            tool_id=KT_AUTHORITY_TOOL_ID,
            turn_id="turn-tool-registry",
            trace_id="tt-tool-registry",
            input_summary={
                "kt_engine": "mock",
                "kt_engine_diagnostics": {
                    "engine_name": "mock",
                    "checkpoint_path": "/Users/lqc/private/save2017model.pkl",
                    "raw_provider_payload": {"secret": "must-not-leak"},
                },
                "kt_diagnosis": {
                    "prediction_probability": 0.58,
                    "weak_concepts": [{"concept_id": "c_fraction_addition"}],
                    "forgetting_risks": [{"concept_id": "c_fraction_addition"}],
                    "evidence": ["mock"],
                },
                "attribution_evidence": {
                    "target_question_id": "q_frac_001",
                    "prediction_probability": 0.58,
                    "provenance": {
                        "dataset_dir": "/Users/lqc/private/assist2017",
                        "checkpoint_id": "fixture-epoch26",
                    },
                    "top_paths": [{"path_id": "mock-path-1"}],
                    "key_history": [{"question_id": "q_frac_001"}],
                },
            },
        ),
    )

    assert registry.find(KT_AUTHORITY_TOOL_ID) is tool
    assert [item.tool_id for item in registry.list_tools()] == [KT_AUTHORITY_TOOL_ID]
    assert registry.manifest()[0]["tool_id"] == KT_AUTHORITY_TOOL_ID
    assert observation.provider_mode == "local_fallback"
    assert observation.fallback_used is True
    assert observation.result_summary["prediction_probability"] == 0.58
    assert observation.result_summary["prediction_facts"]["weak_concepts"] == [
        {"concept_id": "c_fraction_addition"}
    ]
    assert "RAG" in observation.evidence_boundary
    serialized = json.dumps(observation.public_summary(), ensure_ascii=False)
    assert "checkpoint_path" not in serialized
    assert "raw_provider_payload" not in serialized
    assert "/Users/" not in serialized
    assert ".pkl" not in serialized


def test_runtime_records_kt_tool_observation_for_default_local_fallback() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-tool-observation-001",
            "student_id": "student-tool-observation-001",
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
    observations = {
        observation["tool_id"]: observation for observation in expert["tool_observations"]
    }
    observation = observations[KT_AUTHORITY_TOOL_ID]
    rag_observation = observations[RAG_RETRIEVAL_TOOL_ID]
    memory_observation = observations[STUDENT_MEMORY_TOOL_ID]
    trace_event = next(
        event for event in body["teaching_trace"] if event["stage"] == "kt_tool_observation"
    )

    assert expert["tool_registry_manifest"][0]["tool_id"] == KT_AUTHORITY_TOOL_ID
    assert observation["tool_id"] == KT_AUTHORITY_TOOL_ID
    assert observation["provider"] == "mock"
    assert observation["provider_mode"] == "local_fallback"
    assert observation["fallback_used"] is True
    assert observation["status"] == "healthy"
    assert observation["result_summary"]["prediction_probability"] == 0.58
    assert (
        observation["result_summary"]["prediction_probability"]
        == expert["kt_diagnosis"]["prediction_probability"]
    )
    assert (
        observation["result_summary"]["weak_concepts"]
        == expert["kt_diagnosis"]["weak_concepts"]
    )
    assert trace_event["type"] == "observation"
    assert trace_event["actor"] == "kt"
    assert trace_event["metadata"]["tool_id"] == KT_AUTHORITY_TOOL_ID
    assert trace_event["metadata"]["fallback_used"] is True
    assert "kt_tool_observation" in body["teaching_trace_summary"]["stages"]
    assert "rag_tool_observation" in body["teaching_trace_summary"]["stages"]
    assert "memory_tool_observation" in body["teaching_trace_summary"]["stages"]
    assert expert["runtime"]["tool_observation_count"] == 3
    assert set(expert["runtime"]["tool_observation_refs"]) == {
        f"tool_observation:{KT_AUTHORITY_TOOL_ID}",
        f"tool_observation:{RAG_RETRIEVAL_TOOL_ID}",
        f"tool_observation:{STUDENT_MEMORY_TOOL_ID}",
    }
    assert set(expert["learning_turn_context"]["tool_observation_refs"]) == set(
        expert["runtime"]["tool_observation_refs"]
    )
    assert rag_observation["provider_mode"] == "local_fallback"
    assert rag_observation["status"] == "healthy"
    assert rag_observation["result_summary"]["result_count"] == len(expert["rag_sources"])
    assert rag_observation["result_summary"]["citation_refs"]
    assert (
        rag_observation["result_summary"]["authority"]
        == "RAG can support mathematical explanation, citations, examples, theorem notes, "
        "and worked-solution context, but cannot overwrite KT/DGEKT prediction facts."
    )
    assert memory_observation["provider_mode"] == "local_fallback"
    assert memory_observation["status"] == "degraded"
    assert memory_observation["result_summary"]["retrieved_count"] == 0
    assert any(
        gap["gap_type"] == "student_memory"
        for gap in memory_observation["result_summary"]["evidence_gaps"]
    )
    assert (
        memory_observation["result_summary"]["authority"]
        == "Student memory can influence teaching strategy, expression style, review reminders, "
        "and personalization, but cannot directly modify mastery, weak concepts, "
        "prediction probability, or forgetting risks."
    )
    for item in observations.values():
        assert item["provider_mode"] in RUNTIME_PROVIDER_MODES
        assert item["status"] in RUNTIME_READINESS_STATUSES
    overview = expert["trace_overview"]
    for item in overview["tool_observations"]:
        assert item["provider_mode"] in RUNTIME_PROVIDER_MODES
        assert item["status"] in RUNTIME_READINESS_STATUSES
    for item in overview["tool_calls"]:
        assert set(item["provider_modes"]) <= RUNTIME_PROVIDER_MODES
        if item["provider_mode"] is not None:
            assert item["provider_mode"] in RUNTIME_PROVIDER_MODES
        if item["status"] is not None:
            assert item["status"] in RUNTIME_READINESS_STATUSES


def test_runtime_records_empty_rag_observation_without_fabricated_citation(
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
            "session_id": "session-empty-rag-observation",
            "student_id": "student-empty-rag-observation",
            "type": "chat_message",
            "message": "下一步应该学什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    observations = {
        observation["tool_id"]: observation for observation in expert["tool_observations"]
    }
    rag_observation = observations[RAG_RETRIEVAL_TOOL_ID]

    assert rag_observation["status"] == "degraded"
    assert rag_observation["result_summary"]["result_count"] == 0
    assert rag_observation["result_summary"]["sources"] == []
    assert rag_observation["result_summary"]["citation_refs"] == []
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
    assert (
        expert["assembled_context"]["authoritative_kt_facts"]["prediction_probability"]
        == expert["kt_diagnosis"]["prediction_probability"]
        == observations[KT_AUTHORITY_TOOL_ID]["result_summary"]["prediction_probability"]
    )


def test_runtime_observation_aligns_configuration_gap_with_health_readiness() -> None:
    registry = default_tool_registry()
    observation = registry.call(
        RAG_RETRIEVAL_TOOL_ID,
        ToolInvocation(
            tool_id=RAG_RETRIEVAL_TOOL_ID,
            turn_id="turn-runtime-config-gap",
            trace_id="tt-runtime-config-gap",
            input_summary={
                "rag_sources": [],
                "evidence_gaps": [
                    {
                        "gap_type": "provider_configuration_missing",
                        "provider": "openviking",
                        "operation": "search",
                        "reason": "Authorization: Bearer runtime-secret api_key=also-secret",
                        "details": {
                            "safe_summary": "OpenViking live provider 缺配置。",
                            "raw_provider_payload": {"token": "raw-secret"},
                            "local_path": "/Users/lqc/private/vector-cache",
                        },
                    }
                ],
            },
        ),
    )

    summary = observation.public_summary()

    assert summary["provider"] == "openviking"
    assert summary["provider_mode"] == "live_provider"
    assert summary["status"] == "not_configured"
    assert summary["degraded"] is True
    assert summary["result_summary"]["provider_gap_count"] == 1
    assert summary["result_summary"]["provider_gaps"][0]["gap_type"] == (
        "provider_configuration_missing"
    )
    assert summary["result_summary"]["citation_refs"] == []
    serialized = json.dumps(summary, ensure_ascii=False)
    assert "runtime-secret" not in serialized
    assert "also-secret" not in serialized
    assert "raw-secret" not in serialized
    assert "raw_provider_payload" not in serialized
    assert "/Users/" not in serialized


def test_runtime_memory_observation_respects_disabled_and_deleted_controls() -> None:
    disabled_body, disabled_memory_id = _runtime_body_with_controlled_memory("disabled")
    deleted_body, deleted_memory_id = _runtime_body_with_controlled_memory("deleted")

    disabled_observation = _tool_observation(disabled_body, STUDENT_MEMORY_TOOL_ID)
    disabled_summary = disabled_observation["result_summary"]
    assert disabled_observation["status"] == "degraded"
    assert disabled_summary["retrieved_count"] == 0
    assert disabled_summary["selected_count"] == 0
    assert disabled_summary["omitted_count"] >= 1
    assert disabled_summary["disabled_excluded_count"] >= 1
    assert any(
        item["source_ref"] == f"memory:{disabled_memory_id}"
        and item["excluded_reason"] == "学生已禁用该记忆，默认学习上下文已排除。"
        for item in disabled_summary["omitted_assets"]
    )
    assert _student_visible_trace_payload(disabled_body).find(disabled_memory_id) == -1
    assert "参考你之前的学习偏好" not in disabled_body["response"]

    deleted_observation = _tool_observation(deleted_body, STUDENT_MEMORY_TOOL_ID)
    deleted_summary = deleted_observation["result_summary"]
    assert deleted_summary["retrieved_count"] == 0
    assert deleted_summary["selected_count"] == 0
    assert not any(
        item.get("source_ref") == f"memory:{deleted_memory_id}"
        for item in [*deleted_summary["selected_assets"], *deleted_summary["omitted_assets"]]
    )
    assert f"memory:{deleted_memory_id}" not in json.dumps(
        deleted_body["teaching_trace_summary"]["expert_evidence"]["assembled_context"],
        ensure_ascii=False,
    )
    assert _student_visible_trace_payload(deleted_body).find(deleted_memory_id) == -1
    assert "参考你之前的学习偏好" not in deleted_body["response"]


def test_runtime_rag_and_memory_provider_gaps_do_not_override_kt_facts() -> None:
    memories = Mem0StudentMemoryStore(
        client=RaisingMem0Client(TimeoutError("provider timed out")),
        api_key="test-key",
    )
    rag = VikingKnowledgeRAGAdapter(
        provider_name="openviking",
        provider_mode="live_provider",
        collection="assist2017-smoke",
        client=MalformedRAGClient(),
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=memories,
        rag=rag,
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    runtime = MathTutorAgentRuntime(learning_loop=loop)

    response = runtime.handle_event(
        LearningEvent(
            session_id="session-provider-gap-observation",
            student_id="student-provider-gap-observation",
            type="answer_submitted",
            message="我选 1/6",
            payload={"question_id": "q_frac_001", "answer": "1/6"},
        )
    )
    body = response.model_dump(mode="json")
    expert = body["teaching_trace_summary"]["expert_evidence"]
    rag_observation = _tool_observation(body, RAG_RETRIEVAL_TOOL_ID)
    memory_observation = _tool_observation(body, STUDENT_MEMORY_TOOL_ID)
    kt_observation = _tool_observation(body, KT_AUTHORITY_TOOL_ID)

    assert rag_observation["provider"] == "openviking"
    assert rag_observation["provider_mode"] == "live_provider"
    assert rag_observation["status"] == "degraded"
    assert any(
        gap["gap_type"] == "provider_schema_mismatch"
        for gap in rag_observation["result_summary"]["provider_gaps"]
    )
    assert memory_observation["provider"] == "mem0"
    assert memory_observation["provider_mode"] == "live_provider"
    assert memory_observation["status"] == "unavailable"
    assert any(
        gap["gap_type"] == "provider_timeout"
        for gap in memory_observation["result_summary"]["provider_gaps"]
    )
    overview = expert["trace_overview"]
    assert overview["provider_gap_count"] >= 2
    overview_gap_counts = {
        observation["tool_id"]: observation["provider_gap_count"]
        for observation in overview["tool_observations"]
    }
    assert overview_gap_counts[RAG_RETRIEVAL_TOOL_ID] >= 1
    assert overview_gap_counts[STUDENT_MEMORY_TOOL_ID] >= 1
    assert any(
        gap["gap_type"] == "provider_schema_mismatch"
        and gap["provider"] == "openviking"
        for gap in overview["provider_gaps"]
    )
    assert any(
        event["stage"] == "rag_tool_observation"
        and event["provider_gap_count"] >= 1
        and event["provider_mode"] == "live_provider"
        and event["status"] == "degraded"
        for event in overview["stage_events"]
    )
    assert any(
        event["stage"] == "memory_tool_observation"
        and event["provider_gap_count"] >= 1
        and event["provider_mode"] == "live_provider"
        and event["status"] == "unavailable"
        for event in overview["stage_events"]
    )
    assert rag_observation["result_summary"]["citation_refs"] == []
    assert expert["rag_sources"] == []
    assert body["recommended_questions"]
    assert (
        expert["assembled_context"]["authoritative_kt_facts"]["prediction_probability"]
        == expert["kt_diagnosis"]["prediction_probability"]
        == kt_observation["result_summary"]["prediction_probability"]
    )
    assert expert["runtime"]["state_reference_only"] is True
    serialized = json.dumps(body, ensure_ascii=False)
    assert "provider timed out" in serialized
    assert "raw_provider_payload" not in serialized
    assert "embedding_vector" not in serialized


def test_dgekt_tool_observation_preserves_authoritative_facts_and_sanitizes_paths(
    tmp_path,
    monkeypatch,
) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fraction_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            kt_engine=engine,
            store=InMemoryProgressStore(),
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-dgekt-tool-observation",
            "student_id": "student-dgekt-tool-observation",
            "type": "answer_submitted",
            "message": "我选 1/6",
            "payload": {
                "question_id": "q_frac_001",
                "answer": "1/6",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    observation = expert["tool_observations"][0]

    assert observation["provider"] == "dgekt"
    assert observation["provider_mode"] == "live_provider"
    assert observation["result_summary"]["prediction_probability"] == 0.2
    assert (
        observation["result_summary"]["prediction_probability"]
        == expert["kt_diagnosis"]["prediction_probability"]
    )
    assert (
        observation["result_summary"]["weak_concepts"]
        == expert["kt_diagnosis"]["weak_concepts"]
    )
    assert (
        observation["result_summary"]["forgetting_risks"]
        == expert["kt_diagnosis"]["forgetting_risks"]
    )
    assert (
        observation["result_summary"]["attribution"]["prediction_probability"]
        == expert["attribution_evidence"]["prediction_probability"]
    )
    serialized = json.dumps(body, ensure_ascii=False)
    assert str(checkpoint) not in serialized
    assert str(dataset_dir) not in serialized
    assert str(q_matrix) not in serialized
    assert "checkpoint_path" not in serialized
    assert "dataset_dir" not in serialized
    assert "q_matrix_path" not in serialized
    assert ".pkl" not in serialized
    assert "raw_provider_payload" not in serialized


def _runtime_body_with_controlled_memory(status: str) -> tuple[dict[str, Any], str]:
    student_id = f"student-runtime-memory-{status}"
    memories = InMemoryStudentMemoryStore()
    memory = memories.write(
        StudentMemory(
            student_id=student_id,
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
    runtime = MathTutorAgentRuntime(learning_loop=loop)
    first = runtime.handle_event(
        LearningEvent(
            session_id=f"session-runtime-memory-{status}",
            student_id=student_id,
            type="chat_message",
            message="推荐下一题",
            payload={},
        )
    )
    assert "参考你之前的学习偏好" in first.response
    if status == "disabled":
        assert memories.disable(student_id=student_id, memory_id=memory.memory_id) is not None
    elif status == "deleted":
        assert memories.delete(student_id=student_id, memory_id=memory.memory_id) is not None

    second = runtime.handle_event(
        LearningEvent(
            session_id=f"session-runtime-memory-{status}",
            student_id=student_id,
            type="chat_message",
            message="推荐下一题",
            payload={},
        )
    )
    return second.model_dump(mode="json"), memory.memory_id


def _tool_observation(body: dict[str, Any], tool_id: str) -> dict[str, Any]:
    return next(
        observation
        for observation in body["teaching_trace_summary"]["expert_evidence"][
            "tool_observations"
        ]
        if observation["tool_id"] == tool_id
    )


def _student_visible_trace_payload(body: dict[str, Any]) -> str:
    return json.dumps(
        [
            event
            for event in body["teaching_trace"]
            if event.get("visibility") == "student"
        ],
        ensure_ascii=False,
    )
