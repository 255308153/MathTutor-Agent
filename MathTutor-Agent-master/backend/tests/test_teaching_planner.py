from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.planning.teaching_planner import TeachingPlanner
from backend.app.schemas.learning import KTDiagnosis, LearningEvent


def test_teaching_planner_selects_all_four_teaching_type_actions() -> None:
    planner = TeachingPlanner()

    expected = {
        "memory": "quick_review",
        "concept": "concept_explain_self_check",
        "procedure": "worked_example_steps",
        "design": "challenge_reflection",
    }
    for teaching_type, action_type in expected.items():
        plan = planner.plan(
            intent="next_step_advice",
            event=LearningEvent(
                session_id=f"session-{teaching_type}",
                student_id=f"student-{teaching_type}",
                type="chat_message",
                message="推荐下一题",
                payload={},
            ),
            diagnosis=KTDiagnosis(),
            rag_context=[],
            recommended_questions=[
                {
                    "question_id": f"q-{teaching_type}",
                    "teaching_type": teaching_type,
                }
            ],
        )

        assert plan["teaching_type"] == teaching_type
        assert plan["selected_action"]["type"] == action_type


def test_wrong_answer_generates_evidence_based_mistake_diagnosis() -> None:
    planner = TeachingPlanner()

    plan = planner.plan(
        intent="answer_submission",
        event=LearningEvent(
            session_id="session-mistake-001",
            student_id="student-mistake-001",
            type="answer_submitted",
            message="答案是 1/6",
            payload={
                "question_id": "q_frac_001",
                "answer": "1/6",
                "is_correct": False,
                "correct_answer": "3/4",
                "concept_id": "c_fraction_addition",
                "concept_name": "异分母分数加法",
                "teaching_type": "procedure",
                "mistake_patterns": ["没有通分", "分母直接相加"],
            },
        ),
        diagnosis=KTDiagnosis(),
        rag_context=[
            {
                "doc_id": "rag_fraction_addition_mistake",
                "doc_type": "mistake_pattern",
                "title": "常见错因：分母直接相加",
                "source": "demo-rag/fraction_mistakes.md",
                "content": "异分母相加前必须先统一每份大小。",
            }
        ],
        recommended_questions=[],
    )

    mistake = plan["mistake_diagnosis"]
    assert mistake["concept"]["concept_id"] == "c_fraction_addition"
    assert "没有通分" in mistake["mistake_patterns"]
    assert "常见错因：分母直接相加" in mistake["mistake_patterns"]
    assert mistake["rag_evidence"][0]["source"] == "demo-rag/fraction_mistakes.md"
    assert plan["selected_action"]["type"] == "worked_example_steps_after_mistake"


def test_api_exposes_memory_teaching_action_and_planner_trace() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-memory-action-001",
            "student_id": "student-memory-action-001",
            "type": "chat_message",
            "message": "推荐下一题",
            "payload": {"preferred_teaching_type": "memory"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommended_questions"][0]["teaching_type"] == "memory"
    assert body["state_summary"]["next_action"]["type"] == "quick_review"
    assert "记忆型快速复习" in body["response"]
    plan_trace = [event for event in body["teaching_trace"] if event["stage"] == "plan"][0]
    assert plan_trace["metadata"]["planner_decision"] == "deterministic_teaching_planner"
    assert plan_trace["metadata"]["selected_action"]["type"] == "quick_review"


def test_api_wrong_answer_avoids_unsupported_psychological_judgment() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-safe-diagnosis-001",
            "student_id": "student-safe-diagnosis-001",
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
    assert body["state_summary"]["mistake_diagnosis"]["level"] == "concept_and_pattern"
    forbidden = ["不认真", "粗心", "态度不好"]
    assert all(word not in body["response"] for word in forbidden)
    plan_trace = [event for event in body["teaching_trace"] if event["stage"] == "plan"][0]
    assert plan_trace["metadata"]["mistake_diagnosis"]["rag_evidence"]
