from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_chat_message_returns_next_step_response_and_trace() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-chat-001",
            "student_id": "student-chat-001",
            "type": "chat_message",
            "message": "我下一步应该学什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "下一步建议" in body["response"]
    assert body["state_summary"]["intent"] == "next_step_advice"
    assert body["state_summary"]["progress_version"] == 1
    assert body["recommended_questions"][0]["question_id"] == "placeholder-q-risk-1"
    assert [event["stage"] for event in body["teaching_trace"]] == [
        "load_context",
        "diagnose",
        "plan",
        "generate_response",
    ]


def test_answer_submitted_updates_progress_and_returns_trace() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-answer-001",
            "student_id": "student-answer-001",
            "type": "answer_submitted",
            "message": "我选 B",
            "payload": {
                "question_id": "q-demo-001",
                "answer": "B",
                "is_correct": False,
                "time_spent": 73,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "不正确" in body["response"]
    assert body["state_summary"]["intent"] == "answer_submission"
    assert body["state_summary"]["next_action"]["type"] == "review_answer"
    assert body["state_summary"]["progress_version"] == 1
    assert body["recommended_questions"] == []
    assert [event["stage"] for event in body["teaching_trace"]] == [
        "load_context",
        "diagnose",
        "plan",
        "generate_response",
    ]
