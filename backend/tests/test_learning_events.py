from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.storage.content_repository import content_repository


TRACE_STAGES = ["load_context", "diagnose", "plan", "generate_response"]


def assert_core_trace(stages: list[str]) -> None:
    assert stages[:4] == TRACE_STAGES
    assert "memory_update" in stages


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
    assert "下一步先练" in body["response"]
    assert body["state_summary"]["intent"] == "next_step_advice"
    assert body["state_summary"]["progress_version"] == 1
    assert len(body["recommended_questions"]) == 3
    assert body["recommended_questions"][0]["score"] >= body["recommended_questions"][1]["score"]
    assert body["recommended_questions"][0]["reason"]
    assert "score_factors" in body["recommended_questions"][0]
    assert "standard_answer" not in body["recommended_questions"][0]
    assert "explanation" not in body["recommended_questions"][0]
    assert_core_trace([event["stage"] for event in body["teaching_trace"]])


def test_answer_submitted_updates_progress_and_returns_trace() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-answer-001",
            "student_id": "student-answer-001",
            "type": "answer_submitted",
            "message": "我选 1/6",
            "payload": {
                "question_id": "q_frac_001",
                "answer": "1/6",
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
    assert_core_trace([event["stage"] for event in body["teaching_trace"]])
    assert body["teaching_trace"][0]["metadata"]["is_correct"] is False
    assert body["teaching_trace"][0]["metadata"]["grading_source"] == "demo_teaching_content"


def test_recommended_question_then_correct_answer_updates_state() -> None:
    client = TestClient(create_app())

    recommendation = client.post(
        "/api/events",
        json={
            "session_id": "session-correct-001",
            "student_id": "student-correct-001",
            "type": "chat_message",
            "message": "推荐下一题",
            "payload": {},
        },
    ).json()
    question = recommendation["recommended_questions"][0]
    standard_answer = content_repository.get_question(question["question_id"])["standard_answer"]

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-correct-001",
            "student_id": "student-correct-001",
            "type": "answer_submitted",
            "message": f"答案是 {standard_answer}",
            "payload": {
                "question_id": question["question_id"],
                "answer": standard_answer,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "判定为正确" in body["response"]
    assert body["state_summary"]["progress_version"] == 2
    assert body["state_summary"]["next_action"]["type"] == "reinforce_mastery"
    assert body["teaching_trace"][0]["metadata"]["is_correct"] is True


def test_recommended_question_then_wrong_answer_updates_state() -> None:
    client = TestClient(create_app())

    recommendation = client.post(
        "/api/events",
        json={
            "session_id": "session-wrong-001",
            "student_id": "student-wrong-001",
            "type": "chat_message",
            "message": "推荐下一题",
            "payload": {},
        },
    ).json()
    question = recommendation["recommended_questions"][0]

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-wrong-001",
            "student_id": "student-wrong-001",
            "type": "answer_submitted",
            "message": "答案是 1/6",
            "payload": {
                "question_id": question["question_id"],
                "answer": "1/6",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "判定为不正确" in body["response"]
    assert body["state_summary"]["progress_version"] == 2
    assert body["state_summary"]["next_action"]["type"] == "review_answer"
    assert body["state_summary"]["weak_concepts"][0]["concept_id"] == question["concept_id"]
    assert body["teaching_trace"][0]["metadata"]["is_correct"] is False
    assert body["teaching_trace"][1]["metadata"]["weak_concept_count"] == 1
