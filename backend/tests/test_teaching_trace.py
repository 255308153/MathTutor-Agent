from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_event_response_contains_auditable_teaching_trace_summary() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-trace-001",
            "student_id": "student-trace-001",
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
    assert body["trace_id"].startswith("tt-")
    assert body["teaching_trace_summary"]["trace_id"] == body["trace_id"]
    assert body["teaching_trace_summary"]["student_explanation"] == body["response"]
    assert body["teaching_trace_summary"]["stages"] == [
        "runtime_start",
        "load_context",
        "diagnose",
        "context_assemble",
        "plan",
        "generate_response",
        "memory_update",
        "kt_tool_observation",
        "rag_tool_observation",
        "memory_tool_observation",
        "runtime_end",
    ]
    assert "KT facts are authoritative." in body["teaching_trace_summary"]["invariants"]

    expert = body["teaching_trace_summary"]["expert_evidence"]
    learning_turn_context = expert["learning_turn_context"]
    assert learning_turn_context["runtime_name"] == "MathTutorAgentRuntime"
    assert learning_turn_context["subject"] == "math"
    assert learning_turn_context["student_id"] == "student-trace-001"
    assert learning_turn_context["session_id"] == "session-trace-001"
    assert learning_turn_context["intent"] == "answer_submission"
    assert learning_turn_context["learning_event"]["type"] == "answer_submitted"
    assert learning_turn_context["kt_progress_ref"].startswith("progress:student-trace-001:v")
    assert learning_turn_context["kt_progress_version"] == body["state_summary"]["progress_version"]
    assert learning_turn_context["context_asset_refs"]
    assert learning_turn_context["assembled_context_ref"]
    assert f"trace:{body['trace_id']}" in learning_turn_context["trace_refs"]
    assert learning_turn_context["state_reference_only"] is True
    assert "KT remains authoritative." in expert["runtime"]["boundary"]
    assert expert["kt_diagnosis"]["prediction_probability"] == 0.58
    assert expert["attribution_evidence"]["top_paths"][0]["path_id"] == "mock-path-1"
    assert expert["attribution_evidence"]["key_history"]
    assert expert["rag_sources"]
    assert expert["assembled_context"]["authoritative_kt_facts"]["prediction_probability"] == 0.58
    assert expert["planner_decision"]["selected_action"]["type"] == "worked_example_steps_after_mistake"


def test_trace_events_distinguish_student_and_expert_evidence() -> None:
    client = TestClient(create_app())

    body = client.post(
        "/api/events",
        json={
            "session_id": "session-trace-002",
            "student_id": "student-trace-002",
            "type": "chat_message",
            "message": "推荐下一题",
            "payload": {"preferred_teaching_type": "memory"},
        },
    ).json()

    events = body["teaching_trace"]
    by_stage = {event["stage"]: event for event in events}
    assert by_stage["runtime_start"]["actor"] == "runtime"
    assert by_stage["runtime_start"]["type"] == "stage_start"
    assert by_stage["load_context"]["visibility"] == "expert"
    assert by_stage["diagnose"]["actor"] == "kt"
    assert by_stage["kt_tool_observation"]["actor"] == "kt"
    assert by_stage["kt_tool_observation"]["type"] == "observation"
    assert by_stage["rag_tool_observation"]["actor"] == "rag"
    assert by_stage["rag_tool_observation"]["type"] == "observation"
    assert by_stage["memory_tool_observation"]["actor"] == "memory"
    assert by_stage["memory_tool_observation"]["type"] == "observation"
    assert by_stage["context_assemble"]["actor"] == "context"
    assert by_stage["plan"]["actor"] == "planner"
    assert by_stage["generate_response"]["visibility"] == "student"
    assert by_stage["runtime_end"]["actor"] == "runtime"
    assert by_stage["runtime_end"]["type"] == "stage_end"
    assert (
        by_stage["runtime_end"]["metadata"]["kt_progress_version_after"]
        == body["state_summary"]["progress_version"]
    )
    assert by_stage["plan"]["metadata"]["planner_decision"] == "deterministic_teaching_planner"
    assert by_stage["plan"]["evidence_refs"]


def test_learning_turn_context_summary_sanitizes_sensitive_payload_values() -> None:
    client = TestClient(create_app())

    body = client.post(
        "/api/events",
        json={
            "session_id": "session-trace-003",
            "student_id": "student-trace-003",
            "type": "chat_message",
            "message": "请推荐下一步",
            "payload": {
                "api_key": "secret-key",
                "debug_path": "/Users/lqc/private/checkpoints/dgekt.pt",
                "nested": {"token": "secret-token", "visible": "保留"},
                "notes": ["普通提示", "Bearer secret-token"],
            },
        },
    ).json()

    payload = body["teaching_trace_summary"]["expert_evidence"]["learning_turn_context"][
        "learning_event"
    ]["payload"]
    assert "api_key" not in payload
    assert payload["debug_path"] == "<redacted>"
    assert "token" not in payload["nested"]
    assert payload["nested"]["visible"] == "保留"
    assert payload["notes"] == ["普通提示", "<redacted>"]
