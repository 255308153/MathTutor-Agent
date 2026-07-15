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
        "rag_tool_observation",
        "runtime_end",
    ]


def test_v110_context_governance_demo_varies_by_math_learning_intent() -> None:
    client = TestClient(create_app())
    student_id = "student-v110-governance-demo"

    answer = client.post(
        "/api/events",
        json={
            "session_id": "session-v110-answer",
            "student_id": student_id,
            "type": "answer_submitted",
            "message": "我提交答案 1/6。",
            "payload": {"question_id": "q_frac_001", "answer": "1/6"},
        },
    ).json()
    next_step = client.post(
        "/api/events",
        json={
            "session_id": "session-v110-next",
            "student_id": student_id,
            "type": "chat_message",
            "message": "下一步应该练什么？",
            "payload": {},
        },
    ).json()
    concept = client.post(
        "/api/events",
        json={
            "session_id": "session-v110-concept",
            "student_id": student_id,
            "type": "chat_message",
            "message": "请讲解异分母分数加法。",
            "payload": {},
        },
    ).json()

    def expert(turn: dict) -> dict:
        return turn["teaching_trace_summary"]["expert_evidence"]

    def tool_mounts(turn: dict) -> dict[str, str]:
        return {
            item["tool_id"]: item["mount_status"]
            for item in expert(turn)["trace_overview"]["tool_calls"]
        }

    assert [turn["state_summary"]["intent"] for turn in (answer, next_step, concept)] == [
        "answer_submission",
        "next_step_advice",
        "general_chat",
    ]
    assert tool_mounts(answer) == {
        "kt_authoritative_facts": "mounted",
        "rag_retrieval_evidence": "mounted",
        "student_memory_evidence": "skipped",
    }
    assert tool_mounts(next_step) == {
        "kt_authoritative_facts": "mounted",
        "rag_retrieval_evidence": "mounted",
        "student_memory_evidence": "mounted",
    }
    assert tool_mounts(concept)["kt_authoritative_facts"] == "skipped"
    assert not any(event["stage"] == "kt_tool_observation" for event in concept["teaching_trace"])

    for turn in (answer, next_step, concept):
        evidence = expert(turn)
        governance = evidence["context_governance"]
        package = evidence["response_context_package"]
        assert governance["intent"] == turn["state_summary"]["intent"]
        assert governance["response_context_ref"] == package["context_package_id"]
        assert package["governance_id"] == governance["governance_id"]
        assert package["selected_evidence_only"] is True
        assert package["debug_evidence_included"] is False
        assert package["authoritative_kt_facts"] == evidence["assembled_context"][
            "authoritative_kt_facts"
        ]
        assert "raw_provider_payload" not in turn["response"]
        assert "Context Governance" not in turn["response"]
