import json

from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.kt.dgekt_engine import DGEKTStateEngine
from backend.app.main import create_app
from backend.app.runtime import (
    KT_AUTHORITY_TOOL_ID,
    MathToolRegistry,
    ToolInvocation,
    kt_authoritative_facts_tool,
)
from backend.app.storage.progress_store import InMemoryProgressStore
from backend.tests.test_kt_engine_config import (
    patch_fake_dgekt_runtime,
    write_dgekt_fraction_fixture_files,
)


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
    observation = expert["tool_observations"][0]
    trace_event = next(
        event for event in body["teaching_trace"] if event["stage"] == "kt_tool_observation"
    )

    assert expert["tool_registry_manifest"][0]["tool_id"] == KT_AUTHORITY_TOOL_ID
    assert observation["tool_id"] == KT_AUTHORITY_TOOL_ID
    assert observation["provider"] == "mock"
    assert observation["provider_mode"] == "local_fallback"
    assert observation["fallback_used"] is True
    assert observation["status"] == "completed"
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
    assert expert["runtime"]["tool_observation_count"] == 1


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
