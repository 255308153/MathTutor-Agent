from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.memory.store import StudentMemory, memory_store


def test_memory_preference_influences_recommendation_without_overwriting_kt() -> None:
    student_id = "student-memory-pref-001"
    memory_store.write(
        StudentMemory(
            student_id=student_id,
            memory_type="preference",
            content="学生偏好先练比例相关题。",
            evidence={"preferred_concept_id": "c_ratio"},
        )
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-memory-pref-001",
            "student_id": student_id,
            "type": "chat_message",
            "message": "推荐下一题",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "参考你之前的学习偏好" in body["response"]
    assert body["recommended_questions"][0]["concept_id"] == "c_ratio"
    assert body["state_summary"]["weak_concepts"] == []
    load_trace = next(event for event in body["teaching_trace"] if event["stage"] == "load_context")
    assert load_trace["metadata"]["memory_count"] >= 1
    assert load_trace["metadata"]["memory_summaries"][0]["memory_type"] == "preference"


def test_wrong_answer_writes_repeated_mistake_memory() -> None:
    student_id = "student-memory-wrong-001"
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-memory-wrong-001",
            "student_id": student_id,
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
    memory_update_trace = next(
        event for event in body["teaching_trace"] if event["stage"] == "memory_update"
    )
    assert memory_update_trace["stage"] == "memory_update"
    assert memory_update_trace["metadata"]["memory_update_count"] == 1
    recent = memory_store.list_recent(student_id)
    assert recent[0].memory_type == "repeated_mistake"
    assert recent[0].evidence["concept_id"] == "c_fraction_addition"
