from functools import cached_property
from typing import Any

from backend.app.planning.recommender import RiskPrioritizedRecommender
from backend.app.schemas.learning import ConceptState, KTDiagnosis, KTLearningProgress, LearningEvent
from backend.app.storage.content_repository import DemoTeachingContentRepository


def test_recommender_prioritizes_weak_concept_and_avoids_recent_repeat() -> None:
    progress = KTLearningProgress(
        student_id="student-recommender-001",
        concept_states=[
            ConceptState(
                concept_id="c_linear_equation",
                concept_name="一元一次方程",
                mastery=0.35,
                forgetting_risk=0.8,
                recent_accuracy=0.2,
                evidence_count=3,
                status="weak",
            )
        ],
        recent_events=[
            LearningEvent(
                session_id="session-recommender-001",
                student_id="student-recommender-001",
                type="answer_submitted",
                message="刚做过 q_eq_003",
                payload={"question_id": "q_eq_003", "answer": "3", "is_correct": True},
            )
        ],
    )
    diagnosis = KTDiagnosis(
        weak_concepts=[
            {
                "concept_id": "c_linear_equation",
                "concept_name": "一元一次方程",
                "mastery": 0.35,
            }
        ],
        forgetting_risks=[
            {
                "concept_id": "c_linear_equation",
                "concept_name": "一元一次方程",
                "forgetting_risk": 0.8,
            }
        ],
    )

    recommendations = RiskPrioritizedRecommender().recommend(
        progress=progress,
        diagnosis=diagnosis,
        preferences={"preferred_teaching_type": "procedure"},
        limit=3,
    )

    assert recommendations[0]["concept_id"] == "c_linear_equation"
    assert recommendations[0]["question_id"] != "q_eq_003"
    assert recommendations[0]["score"] >= recommendations[1]["score"]
    assert recommendations[0]["score_factors"]["weak_concept_match"] == 1.0
    assert recommendations[0]["score_factors"]["forgetting_urgency"] == 0.8
    assert recommendations[0]["score_factors"]["novelty"] == 1.0
    repeated = [item for item in recommendations if item["question_id"] == "q_eq_003"]
    assert repeated == []


def test_recommender_returns_canonical_teaching_content_payload() -> None:
    progress = KTLearningProgress(student_id="student-recommender-content")
    diagnosis = KTDiagnosis()

    recommendations = RiskPrioritizedRecommender().recommend(
        progress=progress,
        diagnosis=diagnosis,
        limit=1,
    )

    question = recommendations[0]
    assert question["question_id"] == "q_mem_001"
    assert question["stem"] == "快速回答：7 × 8 = ?"
    assert question["answer"] == "56"
    assert question["explanation"] == "7 × 8 是常用乘法事实，结果是 56。"
    assert question["concept_name"] == "乘法口诀事实"
    assert question["difficulty"] == 0.2
    assert question["teaching_type"] == "memory"
    assert "standard_answer" not in question
    assert question["content_availability"]["status"] == "available"
    assert question["provenance"]["mapping_source"] == "xes3g5m_curated_metadata.fixture.json"
    assert question["canonical_mapping"]["xes3g5m_question_id"] == 1
    assert question["canonical_mapping"]["xes3g5m_concept_id"] == 1
    assert question["canonical_mapping"]["kc_routes_reference"]["concept_column_indices"] == [1]
    assert "映射知识点" in question["reason"] or "XES3G5M question" in question["reason"]


def test_recommender_surfaces_missing_teaching_content() -> None:
    progress = KTLearningProgress(student_id="student-recommender-missing-content")
    diagnosis = KTDiagnosis()
    repository = MissingTeachingContentRepository()

    recommendation = RiskPrioritizedRecommender(content=repository).recommend(
        progress=progress,
        diagnosis=diagnosis,
        limit=1,
    )[0]

    assert recommendation["question_id"] == "q_missing_answer"
    assert recommendation["answer"] is None
    assert recommendation["explanation"] is None
    assert recommendation["stem"].startswith("q_missing_answer 缺少题干")
    assert recommendation["content_availability"]["status"] == "partial"
    assert recommendation["content_availability"]["missing_fields"] == [
        "stem",
        "standard_answer",
        "explanation",
    ]
    assert "缺少题干、标准答案、解析" in recommendation["reason"]


class MissingTeachingContentRepository(DemoTeachingContentRepository):
    @cached_property
    def content(self) -> dict[str, Any]:
        return {
            "concept_teaching_type_map": {"c_fraction_addition": "procedure"},
            "questions": [
                {
                    "question_id": "q_missing_answer",
                    "concept_id": "c_fraction_addition",
                    "concept_name": "异分母分数加法",
                    "difficulty": 0.4,
                    "mistake_patterns": [],
                    "rag_doc_ids": [],
                }
            ],
        }

    @cached_property
    def canonical_mapping(self) -> None:
        return None
