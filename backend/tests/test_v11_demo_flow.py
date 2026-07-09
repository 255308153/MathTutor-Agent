from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.storage.content_repository import content_repository


def test_v11_dashboard_demo_flow_has_recommendation_grading_trace_and_evidence() -> None:
    client = TestClient(create_app())
    session_id = "session-v11-demo"
    student_id = "student-v11-demo"

    first_turn = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {},
        },
    ).json()

    first_question = first_turn["recommended_questions"][0]
    assert first_turn["state_summary"]["intent"] == "next_step_advice"
    assert first_turn["trace_id"]
    assert first_turn["teaching_trace_summary"]["expert_evidence"]["recommendations"]
    assert first_turn["teaching_trace_summary"]["expert_evidence"]["rag_sources"]

    wrong_turn = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "answer_submitted",
            "message": "我先故意答错，验证错因路径",
            "payload": {
                "question_id": first_question["question_id"],
                "answer": "__wrong_demo_answer__",
            },
        },
    ).json()

    assert "判定为不正确" in wrong_turn["response"]
    assert wrong_turn["state_summary"]["mistake_diagnosis"]
    assert wrong_turn["state_summary"]["concept_states"]
    assert len(wrong_turn["recommended_questions"]) == 3
    assert wrong_turn["teaching_trace_summary"]["expert_evidence"]["attribution_evidence"][
        "top_paths"
    ]
    assert wrong_turn["teaching_trace_summary"]["expert_evidence"]["rag_sources"]

    next_question = wrong_turn["recommended_questions"][0]
    standard_answer = content_repository.get_question(next_question["question_id"])[
        "standard_answer"
    ]
    correct_turn = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "answer_submitted",
            "message": "这次提交正确答案",
            "payload": {
                "question_id": next_question["question_id"],
                "answer": standard_answer,
            },
        },
    ).json()

    assert "判定为正确" in correct_turn["response"]
    assert correct_turn["state_summary"]["progress_version"] == 3
    assert len(correct_turn["recommended_questions"]) == 3
    assert [event["stage"] for event in correct_turn["teaching_trace"]] == [
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
