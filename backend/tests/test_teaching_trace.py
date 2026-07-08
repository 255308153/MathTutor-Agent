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
        "load_context",
        "diagnose",
        "context_assemble",
        "plan",
        "generate_response",
        "memory_update",
    ]
    assert "KT facts are authoritative." in body["teaching_trace_summary"]["invariants"]

    expert = body["teaching_trace_summary"]["expert_evidence"]
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
    assert by_stage["load_context"]["visibility"] == "expert"
    assert by_stage["diagnose"]["actor"] == "kt"
    assert by_stage["context_assemble"]["actor"] == "context"
    assert by_stage["plan"]["actor"] == "planner"
    assert by_stage["generate_response"]["visibility"] == "student"
    assert by_stage["plan"]["metadata"]["planner_decision"] == "deterministic_teaching_planner"
    assert by_stage["plan"]["evidence_refs"]
