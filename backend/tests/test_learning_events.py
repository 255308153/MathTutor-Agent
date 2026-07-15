from functools import cached_property
from typing import Any

from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.main import create_app
from backend.app.planning.recommender import RiskPrioritizedRecommender
from backend.app.schemas.learning import KTDiagnosis, KTLearningProgress, LearningEvent
from backend.app.storage.content_repository import DemoTeachingContentRepository
from backend.app.storage.content_repository import content_repository
from backend.app.storage.progress_store import InMemoryProgressStore


TRACE_STAGES = [
    "runtime_start",
    "load_context",
    "diagnose",
    "context_assemble",
    "plan",
    "generate_response",
]


def assert_core_trace(stages: list[str]) -> None:
    assert stages[:6] == TRACE_STAGES
    assert "memory_update" in stages
    assert stages[-1] == "runtime_end"


def trace_by_stage(body: dict[str, Any], stage: str) -> dict[str, Any]:
    return next(event for event in body["teaching_trace"] if event["stage"] == stage)


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
    assert body["recommended_questions"][0]["answer"]
    assert body["recommended_questions"][0]["explanation"]
    assert body["recommended_questions"][0]["content_availability"]["status"] == "available"
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
    assert "错因诊断" in body["response"]
    assert body["state_summary"]["intent"] == "answer_submission"
    assert body["state_summary"]["next_action"]["type"] == "worked_example_steps_after_mistake"
    assert body["state_summary"]["mistake_diagnosis"]["concept"]["concept_id"] == "c_fraction_addition"
    assert body["state_summary"]["progress_version"] == 1
    assert len(body["recommended_questions"]) == 3
    assert "下一题建议" in body["response"]
    assert_core_trace([event["stage"] for event in body["teaching_trace"]])
    load_trace = trace_by_stage(body, "load_context")
    assert load_trace["metadata"]["is_correct"] is False
    assert load_trace["metadata"]["grading_source"] == "demo_teaching_content"


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
    assert len(body["recommended_questions"]) == 3
    assert "下一题建议" in body["response"]
    assert trace_by_stage(body, "load_context")["metadata"]["is_correct"] is True


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
    assert body["state_summary"]["next_action"]["type"].endswith("_after_mistake")
    assert body["state_summary"]["weak_concepts"][0]["concept_id"] == question["concept_id"]
    assert len(body["recommended_questions"]) == 3
    assert body["recommended_questions"][0]["question_id"] != question["question_id"]
    assert trace_by_stage(body, "load_context")["metadata"]["is_correct"] is False
    assert trace_by_stage(body, "diagnose")["metadata"]["weak_concept_count"] == 1


def test_recommendation_kt_diagnosis_and_trace_share_canonical_target() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-canonical-alignment-001",
            "student_id": "student-canonical-alignment-001",
            "type": "answer_submitted",
            "message": "我选 55",
            "payload": {
                "question_id": "q_mem_001",
                "answer": "55",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    question = body["recommended_questions"][0]
    plan_event = next(event for event in body["teaching_trace"] if event["stage"] == "plan")
    selected_target = plan_event["metadata"]["selected_canonical_targets"][0]
    expert = body["teaching_trace_summary"]["expert_evidence"]

    assert question["question_id"] == "q_mem_002"
    assert question["answer"] == "54"
    assert question["explanation"] == "六九五十四，所以 6 × 9 = 54。"
    assert question["concept_id"] == "c_multiplication_facts"
    assert question["xes3g5m_question_id"] == 2
    assert question["xes3g5m_concept_id"] == 1
    assert question["canonical_mapping"]["xes3g5m_question_id"] == 2
    assert question["canonical_mapping"]["kc_routes_reference"]["concept_column_indices"] == [1]
    assert body["state_summary"]["weak_concepts"][0]["concept_id"] == question["concept_id"]
    assert expert["kt_diagnosis"]["weak_concepts"][0]["concept_id"] == question["concept_id"]
    assert selected_target["question_id"] == question["question_id"]
    assert selected_target["concept_id"] == question["concept_id"]
    assert selected_target["xes3g5m_question_id"] == question["xes3g5m_question_id"]
    assert selected_target["xes3g5m_concept_id"] == question["xes3g5m_concept_id"]
    assert "question:q_mem_002" in plan_event["evidence_refs"]


def test_api_returns_visible_fallback_when_standard_answer_is_missing(
    monkeypatch,
) -> None:
    repository = MissingAnswerTeachingContentRepository()
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            store=InMemoryProgressStore(),
            content=repository,
            question_recommender=RiskPrioritizedRecommender(content=repository),
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-missing-answer-001",
            "student_id": "student-missing-answer-001",
            "type": "answer_submitted",
            "message": "提交无法判题的内容",
            "payload": {
                "question_id": "q_missing_answer",
                "answer": "3/4",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state_summary"]["next_action"]["type"] == "record_ungraded_answer"
    assert body["state_summary"]["errors"] == [
        "q_missing_answer 缺少标准答案，请补齐教学内容后再用于完整练习。"
    ]
    assert body["state_summary"]["error_records"][0]["category"] == "missing_content"
    assert body["state_summary"]["error_records"][0]["code"] == "missing_standard_answer"
    load_trace = trace_by_stage(body, "load_context")
    assert load_trace["metadata"]["grading_source"] == "missing_teaching_content"
    assert load_trace["metadata"]["evidence_gap_records"][0]["category"] == (
        "missing_content"
    )
    assert load_trace["metadata"]["is_correct"] is None
    assert body["recommended_questions"] == []


def test_api_reports_scorer_failure_without_overwriting_kt(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            kt_engine=ScorerFailureKTStateEngine(),
            store=InMemoryProgressStore(),
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-scorer-failure-001",
            "student_id": "student-scorer-failure-001",
            "type": "answer_submitted",
            "message": "提交触发 scorer failure 的答案",
            "payload": {
                "question_id": "q_frac_001",
                "answer": "__wrong_demo_answer__",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    error_record = body["state_summary"]["error_records"][0]
    expert = body["teaching_trace_summary"]["expert_evidence"]
    attribution = expert["attribution_evidence"]

    assert error_record["category"] == "scorer_failure"
    assert "解释证据 scorer 失败" in error_record["message"]
    assert trace_by_stage(body, "diagnose")["metadata"]["failure_stage"] == "diagnose"
    assert expert["kt_diagnosis"]["prediction_probability"] == 0.41
    assert expert["kt_diagnosis"]["weak_concepts"][0]["concept_id"] == "c_fraction_addition"
    assert attribution["evidence_status"] == "unavailable"
    assert attribution["top_paths"][0]["path_id"] == "scorer-failure"
    assert attribution["top_paths"][0]["partial_evidence"] is True


class MissingAnswerTeachingContentRepository(DemoTeachingContentRepository):
    @cached_property
    def content(self) -> dict[str, Any]:
        return {
            "concept_teaching_type_map": {"c_fraction_addition": "procedure"},
            "questions": [
                {
                    "question_id": "q_missing_answer",
                    "stem": "计算：1/2 + 1/4 = ?",
                    "explanation": "先通分，再相加。",
                    "concept_id": "c_fraction_addition",
                    "concept_name": "异分母分数加法",
                    "difficulty": 0.35,
                    "mistake_patterns": ["没有通分"],
                    "rag_doc_ids": [],
                }
            ],
        }

    @cached_property
    def canonical_mapping(self) -> None:
        return None


class ScorerFailureKTStateEngine:
    engine_name = "fake-scorer-failure"

    @property
    def diagnostics(self) -> dict[str, str]:
        return {"engine_name": self.engine_name}

    def update_from_event(
        self,
        progress: KTLearningProgress,
        event: LearningEvent,
    ) -> KTLearningProgress:
        progress.current_session_id = event.session_id
        progress.recent_events.append(event)
        progress.version += 1
        return progress

    def diagnose(
        self,
        progress: KTLearningProgress,
        target_question_id: str | None = None,
    ) -> KTDiagnosis:
        return KTDiagnosis(
            weak_concepts=[
                {
                    "concept_id": "c_fraction_addition",
                    "concept_name": "异分母分数加法",
                    "mastery": 0.41,
                }
            ],
            forgetting_risks=[],
            prediction_probability=0.41,
            evidence=["fake KT diagnosis for scorer failure test"],
            metadata={
                "engine_name": self.engine_name,
                "prediction_facts": {
                    "prediction_probability": 0.41,
                    "weak_concepts": [
                        {
                            "concept_id": "c_fraction_addition",
                            "concept_name": "异分母分数加法",
                            "mastery": 0.41,
                        }
                    ],
                    "forgetting_risks": [],
                },
            },
        )

    def explain_prediction(
        self,
        progress: KTLearningProgress,
        target_question_id: str,
    ):
        raise RuntimeError("synthetic scorer failure")
