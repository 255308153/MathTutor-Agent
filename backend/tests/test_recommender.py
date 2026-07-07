from backend.app.planning.recommender import RiskPrioritizedRecommender
from backend.app.schemas.learning import ConceptState, KTDiagnosis, KTLearningProgress, LearningEvent


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
