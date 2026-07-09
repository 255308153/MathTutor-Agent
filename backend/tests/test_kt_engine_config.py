import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.core.config import MathTutorSettings
from backend.app.kt.dgekt_engine import (
    DGEKTCheckpointError,
    DGEKTConfigurationError,
    DGEKTRuntime,
    DGEKTStateEngine,
    DGEKTUnsupportedTargetError,
)
from backend.app.kt.factory import create_kt_engine
from backend.app.kt.mock_engine import MockKTStateEngine
from backend.app.schemas.learning import (
    AttributionEvidence,
    ConceptState,
    KTDiagnosis,
    KTLearningProgress,
    LearningEvent,
)
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.storage.progress_store import InMemoryProgressStore


ROOT = Path(__file__).resolve().parents[2]
DGEKT_OFFLINE_EVIDENCE_FIXTURE = ROOT / "data" / "dgekt" / "offline_evidence_fixture"


class FakeDGEKTModel:
    training = False

    def __call__(self, tensor):
        import torch

        batch_size = tensor.shape[0]
        logits = torch.full((batch_size, 50, 3162), -1.3862944, device=tensor.device)
        return logits, logits, logits


def write_dgekt_fixture_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    checkpoint = tmp_path / "save2017model.pkl"
    checkpoint.write_bytes(b"not-a-real-checkpoint")
    q_matrix = tmp_path / "2017.csv"
    q_matrix.write_text(
        "\n".join("1,0" if index % 2 == 0 else "0,1" for index in range(30)),
        encoding="utf-8",
    )
    dataset_dir = tmp_path / "assist2017"
    dataset_dir.mkdir()
    (dataset_dir / "assist2017_pid_train.csv").write_text("train\n", encoding="utf-8")
    (dataset_dir / "assist2017_pid_test.csv").write_text("test\n", encoding="utf-8")
    return checkpoint, dataset_dir, q_matrix


def write_dgekt_fraction_fixture_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    rows = ["1,0" if index % 2 == 0 else "0,1" for index in range(30)]
    rows[2] = "0,1"
    q_matrix.write_text("\n".join(rows), encoding="utf-8")
    return checkpoint, dataset_dir, q_matrix


def patch_fake_dgekt_runtime(monkeypatch: pytest.MonkeyPatch, checkpoint: Path) -> None:
    def fake_load_runtime(self: DGEKTStateEngine, *, device: str) -> DGEKTRuntime:
        return DGEKTRuntime(
            model=FakeDGEKTModel(),
            device=device,
            metadata={
                "engine_name": "dgekt",
                "dataset": "assist2017",
                "checkpoint_path": str(checkpoint),
                "epoch": 26,
                "auc": 0.7866464407565317,
                "acc": 0.728796544573157,
                "device": device,
                "model_eval": True,
                "optimizer_state_available": True,
            },
        )

    monkeypatch.setattr(DGEKTStateEngine, "_load_runtime", fake_load_runtime)


def test_default_kt_engine_is_mock() -> None:
    settings = MathTutorSettings()

    assert settings.kt_engine == "mock"
    assert isinstance(create_kt_engine(settings), MockKTStateEngine)


def test_mock_engine_ignores_configured_offline_evidence_path() -> None:
    settings = MathTutorSettings(
        kt_engine="mock",
        dgekt_offline_evidence_dir="/path/that/does/not/exist",
    )

    assert isinstance(create_kt_engine(settings), MockKTStateEngine)


def test_unsupported_kt_engine_fails_during_config_parse() -> None:
    with pytest.raises(ValidationError):
        MathTutorSettings(kt_engine="unknown")


def test_dgekt_engine_requires_checkpoint_path() -> None:
    settings = MathTutorSettings(kt_engine="dgekt")

    with pytest.raises(DGEKTConfigurationError, match="MATHTUTOR_DGEKT_CHECKPOINT_PATH"):
        create_kt_engine(settings)


def test_dgekt_validation_reports_missing_dataset_files(tmp_path: Path) -> None:
    checkpoint = tmp_path / "save2017model.pkl"
    checkpoint.write_bytes(b"not-a-real-checkpoint")
    q_matrix = tmp_path / "2017.csv"
    q_matrix.write_text("1,0,1\n", encoding="utf-8")
    dataset_dir = tmp_path / "assist2017"
    dataset_dir.mkdir()

    with pytest.raises(DGEKTConfigurationError, match="assist2017_pid_train.csv"):
        DGEKTStateEngine.validate_configuration(
            dataset="assist2017",
            checkpoint_path=str(checkpoint),
            dataset_dir=str(dataset_dir),
            q_matrix_path=str(q_matrix),
        )


def test_dgekt_validation_accepts_required_local_files(tmp_path: Path) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)

    paths = DGEKTStateEngine.validate_configuration(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )

    assert paths.checkpoint_path == checkpoint
    assert paths.dataset_dir == dataset_dir
    assert paths.q_matrix_path == q_matrix


def test_dgekt_checkpoint_validation_requires_expected_keys(tmp_path: Path) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)

    engine = object.__new__(DGEKTStateEngine)
    engine.paths = DGEKTStateEngine.validate_configuration(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )

    with pytest.raises(DGEKTCheckpointError, match="model_state_dict"):
        engine._validate_checkpoint_dict({"epoch": 1, "auc": 0.7, "acc": 0.6})


def test_dgekt_engine_matches_kt_contract_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    progress = KTLearningProgress(student_id="student-dgekt-contract")
    event = LearningEvent(
        session_id="session-dgekt-contract",
        student_id="student-dgekt-contract",
        type="answer_submitted",
        message="答案是 1/2",
        payload={"question_id": "assist2017:1", "is_correct": True},
    )

    dgekt_updated = engine.update_from_event(progress, event)
    dgekt_diagnosis = engine.diagnose(dgekt_updated, target_question_id="assist2017:2")
    dgekt_evidence = engine.explain_prediction(dgekt_updated, target_question_id="assist2017:2")

    mock_progress = KTLearningProgress(student_id="student-mock-contract")
    mock_updated = MockKTStateEngine().update_from_event(mock_progress, event)
    mock_diagnosis = MockKTStateEngine().diagnose(mock_updated, target_question_id="assist2017:2")
    mock_evidence = MockKTStateEngine().explain_prediction(
        mock_updated,
        target_question_id="assist2017:2",
    )

    for diagnosis in (dgekt_diagnosis, mock_diagnosis):
        assert isinstance(diagnosis, KTDiagnosis)
        assert isinstance(diagnosis.weak_concepts, list)
        assert isinstance(diagnosis.forgetting_risks, list)
        assert isinstance(diagnosis.evidence, list)

    for evidence in (dgekt_evidence, mock_evidence):
        assert isinstance(evidence, AttributionEvidence)
        assert evidence.target_question_id == "assist2017:2"
        assert isinstance(evidence.top_paths, list)
        assert isinstance(evidence.key_history, list)
        assert isinstance(evidence.weak_concepts, list)

    assert dgekt_updated.version == 1
    assert engine.diagnostics["engine_name"] == "dgekt"
    assert engine.diagnostics["model_eval"] is True
    assert "epoch=26" in dgekt_diagnosis.evidence[1]
    assert dgekt_evidence.top_paths[0]["engine"] == "dgekt"
    assert dgekt_evidence.top_paths[0]["partial_evidence"] is True
    assert dgekt_evidence.top_paths[0]["evidence_status"] == "partial"
    assert dgekt_evidence.top_paths[0]["history_assist2017_question_id"] == 1
    assert dgekt_evidence.top_paths[0]["target_assist2017_question_id"] == 2
    assert "concept_relation_strength" in dgekt_evidence.top_paths[0]
    assert "path_weight" in dgekt_evidence.top_paths[0]
    assert dgekt_evidence.top_paths[0]["path_strength"] == dgekt_evidence.top_paths[0]["path_weight"]
    assert "relation_strength" in dgekt_evidence.top_paths[0]
    assert dgekt_evidence.top_paths[0]["relation_source"] == "q_matrix_recent_history_proxy"
    assert dgekt_evidence.key_history[0]["assist2017_question_id"] == 1
    assert "ASSIST2017 Q1" in dgekt_evidence.key_history[0]["readable_summary"]
    assert dgekt_evidence.prediction_probability == 0.2
    assert dgekt_diagnosis.prediction_probability == 0.2


def test_dgekt_online_scorer_evidence_shape_and_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    progress = KTLearningProgress(
        student_id="student-dgekt-scorer",
        recent_events=[
            LearningEvent(
                session_id="session-dgekt-scorer",
                student_id="student-dgekt-scorer",
                type="answer_submitted",
                payload={
                    "question_id": "q_frac_001",
                    "concept_id": "c_fraction_addition",
                    "concept_name": "异分母分数加法",
                    "assist2017_question_id": 1,
                    "is_correct": False,
                },
            )
        ],
    )

    evidence = engine.explain_prediction(progress, target_question_id="assist2017:3")
    top_path = evidence.top_paths[0]

    assert evidence.scorer["name"] == "dgekt_online_graph_proxy_scorer"
    assert evidence.scorer["relation_source"] == "q_matrix_recent_history_proxy"
    assert evidence.provenance["offline_path_scorer_available"] is False
    assert evidence.raw_model_target["assist2017_question_id"] == 3
    assert evidence.canonical_mapping["q_matrix_reference"]["concept_columns"] == [1]
    assert evidence.mapped_teaching_content["mapping_status"] == "q_matrix_only"
    assert evidence.partial_evidence is True
    assert "offline DGEKT explainability path scorer" in evidence.partial_evidence_reason
    assert top_path["scorer_name"] == "dgekt_online_graph_proxy_scorer"
    assert top_path["path_strength"] == top_path["path_weight"]
    assert top_path["relation_strength"] == 1.0
    assert top_path["relation_source"] == "q_matrix_recent_history_proxy"
    assert top_path["weak_concept_hit"] is True
    assert top_path["weak_concept_evidence"][0]["concept_id"] == "c_fraction_addition"
    assert top_path["partial_evidence"] is True
    assert "offline DGEKT explainability path scorer" in top_path["partial_evidence_reason"]
    assert "ASSIST2017 Q1" in evidence.key_history[0]["readable_summary"]


def test_dgekt_online_scorer_marks_no_history_partial_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )

    evidence = engine.explain_prediction(
        KTLearningProgress(student_id="student-dgekt-no-history"),
        target_question_id="assist2017:1",
    )

    assert evidence.partial_evidence is True
    assert evidence.evidence_status == "partial"
    assert evidence.partial_evidence_reason == "No graded ASSIST2017 answer history is available."
    assert evidence.scorer["name"] == "dgekt_online_graph_proxy_scorer"
    assert evidence.top_paths[0]["partial_evidence_reason"] == (
        "No graded ASSIST2017 answer history is available."
    )
    assert evidence.top_paths[0]["path_strength"] == 0.0
    assert evidence.key_history == []


def test_dgekt_offline_evidence_hit_returns_complete_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fraction_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        checkpoint_id="dgekt-assist2017-fixture-epoch26",
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
        offline_evidence_dir=str(DGEKT_OFFLINE_EVIDENCE_FIXTURE),
    )
    progress = KTLearningProgress(
        student_id="student-dgekt-offline-fixture",
        recent_events=[
            LearningEvent(
                session_id="session-dgekt-offline-fixture",
                student_id="student-dgekt-offline-fixture",
                type="answer_submitted",
                payload={
                    "question_id": "q_frac_001",
                    "concept_id": "c_fraction_addition",
                    "concept_name": "异分母分数加法",
                    "assist2017_question_id": 3,
                    "assist2017_concept_id": 2,
                    "is_correct": False,
                },
            )
        ],
    )

    diagnosis = engine.diagnose(progress, target_question_id="q_frac_001")
    evidence = engine.explain_prediction(progress, target_question_id="q_frac_001")

    assert diagnosis.prediction_probability == 0.2
    assert diagnosis.weak_concepts[0]["mastery"] == 0.2
    assert evidence.prediction_probability == 0.2
    assert evidence.evidence_status == "complete"
    assert evidence.evidence_source == "offline"
    assert evidence.partial_evidence is False
    assert evidence.scorer["name"] == "dgekt_offline_path_scorer"
    assert evidence.raw_model_target["sample_id"] == "fixture-s1-t2-q3"
    assert evidence.raw_model_target["canonical_question_id"] == "q_frac_001"
    assert evidence.mapped_teaching_content["concept_id"] == "c_fraction_addition"
    assert evidence.top_paths[0]["path_id"] == "path-fixture-history-q3"
    assert evidence.top_paths[0]["path_score"] == 0.842
    assert evidence.top_paths[0]["risk_score"] == 0.8
    assert evidence.top_paths[0]["mastery_score"] == 0.2
    assert evidence.path_ablation[0]["impact"] == 0.16
    assert evidence.evidence_gaps == []


def test_dgekt_offline_target_gap_keeps_online_partial_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fraction_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        checkpoint_id="dgekt-assist2017-fixture-epoch26",
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
        offline_evidence_dir=str(DGEKT_OFFLINE_EVIDENCE_FIXTURE),
    )
    progress = KTLearningProgress(
        student_id="student-dgekt-offline-fixture",
        recent_events=[
            LearningEvent(
                session_id="session-dgekt-offline-gap",
                student_id="student-dgekt-offline-fixture",
                type="answer_submitted",
                payload={
                    "question_id": "q_frac_001",
                    "concept_id": "c_fraction_addition",
                    "concept_name": "异分母分数加法",
                    "assist2017_question_id": 3,
                    "assist2017_concept_id": 2,
                    "is_correct": False,
                },
            )
        ],
    )

    evidence = engine.explain_prediction(progress, target_question_id="assist2017:4")

    assert evidence.evidence_status == "unavailable"
    assert evidence.partial_evidence is True
    assert "partial proxy fallback" in evidence.partial_evidence_reason
    assert evidence.evidence_gaps[0]["category"] == "target_not_found"
    assert evidence.top_paths[0]["partial_evidence"] is True
    assert evidence.top_paths[0]["offline_evidence_status"] == "unavailable"
    assert evidence.scorer["fallback_scorer"]["name"] == "dgekt_online_graph_proxy_scorer"


def test_dgekt_explicit_unsupported_target_fails_with_typed_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    progress = KTLearningProgress(
        student_id="student-dgekt-unsupported-target",
        recent_events=[
            LearningEvent(
                session_id="session-dgekt-unsupported-target",
                student_id="student-dgekt-unsupported-target",
                type="answer_submitted",
                payload={
                    "question_id": "q_frac_001",
                    "assist2017_question_id": 1,
                    "is_correct": True,
                },
            )
        ],
    )

    with pytest.raises(DGEKTUnsupportedTargetError, match="out of range"):
        engine.diagnose(progress, target_question_id="assist2017:9999")


def test_dgekt_builds_one_hot_sequence_from_recent_answer_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    progress = KTLearningProgress(
        student_id="student-dgekt-input",
        recent_events=[
            LearningEvent(
                session_id="session-dgekt-input",
                student_id="student-dgekt-input",
                type="answer_submitted",
                payload={
                    "question_id": "q_frac_001",
                    "assist2017_question_id": 1,
                    "is_correct": True,
                },
            ),
            LearningEvent(
                session_id="session-dgekt-input",
                student_id="student-dgekt-input",
                type="answer_submitted",
                payload={
                    "question_id": "q_frac_002",
                    "assist2017_question_id": "assist2017:2",
                    "assist2017_concept_id": 2,
                    "is_correct": False,
                },
            ),
        ],
    )

    inference_input = engine.build_inference_input(progress)

    assert inference_input is not None
    assert inference_input.question_ids == [1, 2]
    assert inference_input.answers == [1, 0]
    assert inference_input.concept_ids == [1, 2]
    assert inference_input.tensor.shape == (1, 50, 6324)
    assert inference_input.tensor[0, 48, 0].item() == 1.0
    assert inference_input.tensor[0, 49, 3163].item() == 1.0


def test_dgekt_mapping_missing_question_id_fails_clearly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    progress = KTLearningProgress(
        student_id="student-dgekt-missing",
        recent_events=[
            LearningEvent(
                session_id="session-dgekt-missing",
                student_id="student-dgekt-missing",
                type="answer_submitted",
                payload={"question_id": "q_frac_001", "is_correct": True},
            )
        ],
    )

    with pytest.raises(Exception, match="Cannot map MathTutor question_id"):
        engine.build_inference_input(progress)


def test_dgekt_mapping_inconsistent_concept_fails_clearly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    progress = KTLearningProgress(
        student_id="student-dgekt-concept",
        recent_events=[
            LearningEvent(
                session_id="session-dgekt-concept",
                student_id="student-dgekt-concept",
                type="answer_submitted",
                payload={
                    "assist2017_question_id": 1,
                    "assist2017_concept_id": 2,
                    "is_correct": True,
                },
            )
        ],
    )

    with pytest.raises(Exception, match="inconsistent with Q-matrix"):
        engine.build_inference_input(progress)


def test_api_answer_submission_can_use_dgekt_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient
    from backend.app.api import events as events_api
    from backend.app.main import create_app

    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            kt_engine=engine,
            store=InMemoryProgressStore(),
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-api-dgekt",
            "student_id": "student-api-dgekt",
            "type": "answer_submitted",
            "message": "我选 1/6",
            "payload": {
                "question_id": "q_frac_001",
                "answer": "1/6",
                "assist2017_question_id": 1,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    diagnose_event = next(event for event in body["teaching_trace"] if event["stage"] == "diagnose")
    assert body["state_summary"]["intent"] == "answer_submission"
    assert diagnose_event["metadata"]["kt_engine"] == "dgekt"
    assert diagnose_event["metadata"]["prediction_probability"] == 0.2
    attribution = body["teaching_trace_summary"]["expert_evidence"]["attribution_evidence"]
    assert attribution["prediction_probability"] == 0.2
    assert attribution["top_paths"][0]["partial_evidence"] is True
    assert attribution["top_paths"][0]["evidence_status"] == "partial"
    assert attribution["top_paths"][0]["path_strength"] == attribution["top_paths"][0]["path_weight"]
    assert attribution["top_paths"][0]["relation_source"] == "q_matrix_recent_history_proxy"
    assert attribution["top_paths"][0]["weak_concept_hit"] is True
    assert attribution["key_history"][0]["assist2017_question_id"] == 1
    assert "ASSIST2017 Q1" in attribution["key_history"][0]["readable_summary"]
    attribution_chain = diagnose_event["metadata"]["attribution_chain"]
    assert attribution_chain["raw_model_target"]["assist2017_question_id"] == 1
    assert attribution_chain["mapped_teaching_content"]["question_id"] == "q_frac_001"
    assert (
        attribution_chain["attribution_evidence"]["scorer"]["name"]
        == "dgekt_online_graph_proxy_scorer"
    )
    assert attribution_chain["attribution_evidence"]["weak_concept_hit_count"] == 1
    assert "partial_evidence" not in body["response"]
    assert "top_paths" not in body["response"]
    assert "DGEKT inference input built" in diagnose_event["metadata"]["evidence"][2]
    assert (
        body["teaching_trace_summary"]["expert_evidence"]["kt_diagnosis"]["metadata"][
            "model_provenance"
        ]["engine_name"]
        == "dgekt"
    )
    assert engine.diagnostics["last_inference_input"]["question_ids"] == [1]


def test_dgekt_prediction_facts_influence_recommendation_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    progress = KTLearningProgress(
        student_id="student-dgekt-recommend",
        recent_events=[
            LearningEvent(
                session_id="session-dgekt-recommend",
                student_id="student-dgekt-recommend",
                type="answer_submitted",
                payload={
                    "question_id": "q_frac_001",
                    "concept_id": "c_fraction_addition",
                    "concept_name": "异分母分数加法",
                    "assist2017_question_id": 1,
                    "is_correct": False,
                },
            )
        ],
    )
    diagnosis = engine.diagnose(progress, target_question_id="q_frac_001")

    from backend.app.planning.recommender import RiskPrioritizedRecommender

    recommendations = RiskPrioritizedRecommender().recommend(
        progress=progress,
        diagnosis=diagnosis,
        limit=3,
    )

    assert diagnosis.prediction_probability == 0.2
    assert diagnosis.weak_concepts[0]["concept_id"] == "c_fraction_addition"
    assert recommendations[0]["concept_id"] == "c_fraction_addition"
    assert recommendations[0]["score_factors"]["prediction_risk"] == 0.8
    assert "DGEKT 预测答对概率偏低" in recommendations[0]["reason"]


def test_dgekt_dashboard_smoke_flow_uses_demo_assist2017_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient
    from backend.app.api import events as events_api
    from backend.app.main import create_app

    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            kt_engine=engine,
            store=InMemoryProgressStore(),
        ),
    )
    client = TestClient(create_app())
    session_id = "session-v12-dgekt-dashboard"
    student_id = "student-v12-dgekt-dashboard"

    next_step = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {},
        },
    ).json()
    first_question = next_step["recommended_questions"][0]

    assert isinstance(first_question["assist2017_question_id"], int)

    submitted = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "answer_submitted",
            "message": "提交 dashboard 推荐题答案",
            "payload": {
                "question_id": first_question["question_id"],
                "answer": "__wrong_demo_answer__",
                "assist2017_question_id": first_question["assist2017_question_id"],
            },
        },
    )

    assert submitted.status_code == 200
    body = submitted.json()
    diagnose_event = next(event for event in body["teaching_trace"] if event["stage"] == "diagnose")
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assert body["state_summary"]["intent"] == "answer_submission"
    assert body["state_summary"]["progress_version"] == 2
    assert body["recommended_questions"]
    assert diagnose_event["metadata"]["kt_engine"] == "dgekt"
    assert diagnose_event["metadata"]["kt_engine_diagnostics"]["epoch"] == 26
    assert diagnose_event["metadata"]["prediction_facts"]["prediction_probability"] == 0.2
    assert expert["kt_diagnosis"]["metadata"]["model_provenance"]["auc"] == 0.7866464407565317
    assert expert["attribution_evidence"]["prediction_probability"] == 0.2
    assert expert["attribution_evidence"]["top_paths"][0]["partial_evidence"] is True


def test_v13_dgekt_e2e_smoke_keeps_one_canonical_concept_across_learning_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient
    from backend.app.api import events as events_api
    from backend.app.main import create_app

    checkpoint, dataset_dir, q_matrix = write_dgekt_fraction_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    session_id = "session-v13-dgekt-e2e"
    student_id = "student-v13-dgekt-e2e"
    canonical_concept_id = "c_fraction_addition"
    store = InMemoryProgressStore()
    store.save(
        KTLearningProgress(
            student_id=student_id,
            concept_states=[
                ConceptState(
                    concept_id=canonical_concept_id,
                    concept_name="异分母分数加法",
                    teaching_type="procedure",
                    mastery=0.17,
                    forgetting_risk=0.8,
                    recent_accuracy=0.2,
                    evidence_count=2,
                    status="weak",
                )
            ],
            weak_concepts=[
                {
                    "concept_id": canonical_concept_id,
                    "concept_name": "异分母分数加法",
                    "mastery": 0.17,
                }
            ],
            forgetting_risks=[
                {
                    "concept_id": canonical_concept_id,
                    "concept_name": "异分母分数加法",
                    "forgetting_risk": 0.8,
                }
            ],
        )
    )
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            kt_engine=engine,
            store=store,
        ),
    )
    client = TestClient(create_app())

    next_step = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {
                "preferred_concept_id": canonical_concept_id,
                "preferred_teaching_type": "procedure",
            },
        },
    ).json()
    mapped_question = next_step["recommended_questions"][0]

    assert mapped_question["question_id"] == "q_frac_001"
    assert mapped_question["concept_id"] == canonical_concept_id
    assert mapped_question["assist2017_question_id"] == 3
    assert mapped_question["assist2017_concept_id"] == 2
    assert mapped_question["canonical_mapping"]["q_matrix_reference"]
    assert "对齐 ASSIST2017 question 3" in mapped_question["reason"]

    answer_response = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "answer_submitted",
            "message": "我先故意答错，验证 V1.3 真实路径",
            "payload": {
                "question_id": mapped_question["question_id"],
                "answer": "__wrong_demo_answer__",
            },
        },
    )

    assert answer_response.status_code == 200
    body = answer_response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    stages = {event["stage"]: event for event in body["teaching_trace"]}
    kt_diagnosis = expert["kt_diagnosis"]
    attribution = expert["attribution_evidence"]
    rag_sources = expert["rag_sources"]
    mistake = body["state_summary"]["mistake_diagnosis"]
    assembled = expert["assembled_context"]
    plan_metadata = stages["plan"]["metadata"]

    assert body["teaching_trace_summary"]["stages"] == [
        "runtime_start",
        "load_context",
        "diagnose",
        "context_assemble",
        "plan",
        "generate_response",
        "memory_update",
        "runtime_end",
    ]
    assert "判定为不正确" in body["response"]
    assert "错因诊断" in body["response"]
    assert "demo-rag/" in body["response"]

    assert kt_diagnosis["prediction_probability"] == 0.2
    assert kt_diagnosis["weak_concepts"][0]["concept_id"] == canonical_concept_id
    assert kt_diagnosis["forgetting_risks"][0]["concept_id"] == canonical_concept_id
    assert assembled["authoritative_kt_facts"]["weak_concepts"] == kt_diagnosis["weak_concepts"]
    assert assembled["authoritative_kt_facts"]["prediction_probability"] == 0.2

    assert any(source["concept_id"] == canonical_concept_id for source in rag_sources)
    assert any(source["question_id"] == "q_frac_001" for source in rag_sources)
    assert any(source["assist2017_question_id"] == 3 for source in rag_sources)
    assert mistake["concept"]["concept_id"] == canonical_concept_id
    assert any("常见错因" in pattern for pattern in mistake["mistake_patterns"])

    assert attribution["prediction_probability"] == 0.2
    assert attribution["target_concept_id"] == canonical_concept_id
    assert attribution["target_assist2017_question_id"] == 3
    assert attribution["target_assist2017_concept_id"] == 2
    assert attribution["mapped_teaching_content"]["question_id"] == "q_frac_001"
    assert attribution["key_history"][0]["concept_id"] == canonical_concept_id
    assert attribution["top_paths"][0]["weak_concept_hit"] is True
    assert attribution["top_paths"][0]["weak_concept_evidence"][0]["concept_id"] == (
        canonical_concept_id
    )

    attribution_chain = stages["diagnose"]["metadata"]["attribution_chain"]
    assert attribution_chain["raw_model_target"]["assist2017_question_id"] == 3
    assert attribution_chain["mapped_teaching_content"]["concept_id"] == canonical_concept_id
    assert attribution_chain["attribution_evidence"]["weak_concept_hit_count"] == 1
    assert plan_metadata["mistake_diagnosis"]["concept"]["concept_id"] == canonical_concept_id
    assert any(
        target["concept_id"] == canonical_concept_id
        for target in plan_metadata["selected_canonical_targets"]
    )
    assert any(
        source["concept_id"] == canonical_concept_id
        for source in plan_metadata["planner_evidence"]["rag_sources"]
    )
    assert any(
        asset["concept_id"] == canonical_concept_id
        for asset in assembled["normalized_context"]["knowledge_resource"]
    )
    if assembled["normalized_context"]["student_memory"]:
        assert any(
            memory.get("included_reason")
            for memory in assembled["normalized_context"]["student_memory"]
        )
    else:
        assert any(gap["reason"] == "无可用记忆" for gap in assembled["evidence_gaps"])


def test_v16_offline_evidence_flows_from_recommendation_to_answer_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient
    from backend.app.api import events as events_api
    from backend.app.main import create_app

    checkpoint, dataset_dir, q_matrix = write_dgekt_fraction_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        checkpoint_id="dgekt-assist2017-fixture-epoch26",
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
        offline_evidence_dir=str(DGEKT_OFFLINE_EVIDENCE_FIXTURE),
    )
    session_id = "session-v16-dgekt-offline-e2e"
    student_id = "student-dgekt-offline-fixture"
    canonical_question_id = "q_frac_001"
    canonical_concept_id = "c_fraction_addition"
    store = InMemoryProgressStore()
    store.save(
        KTLearningProgress(
            student_id=student_id,
            concept_states=[
                ConceptState(
                    concept_id=canonical_concept_id,
                    concept_name="异分母分数加法",
                    teaching_type="procedure",
                    mastery=0.18,
                    forgetting_risk=0.8,
                    recent_accuracy=0.2,
                    evidence_count=1,
                    status="weak",
                )
            ],
            weak_concepts=[
                {
                    "concept_id": canonical_concept_id,
                    "concept_name": "异分母分数加法",
                    "mastery": 0.18,
                }
            ],
            forgetting_risks=[
                {
                    "concept_id": canonical_concept_id,
                    "concept_name": "异分母分数加法",
                    "forgetting_risk": 0.8,
                }
            ],
        )
    )
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            kt_engine=engine,
            store=store,
        ),
    )
    client = TestClient(create_app())

    recommendation_response = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {
                "preferred_concept_id": canonical_concept_id,
                "preferred_teaching_type": "procedure",
            },
        },
    )
    assert recommendation_response.status_code == 200
    recommended_question = recommendation_response.json()["recommended_questions"][0]
    assert recommended_question["question_id"] == canonical_question_id
    assert recommended_question["concept_id"] == canonical_concept_id
    assert recommended_question["assist2017_question_id"] == 3

    answer_response = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "answer_submitted",
            "message": "我选 1/6",
            "payload": {
                "question_id": recommended_question["question_id"],
                "answer": "1/6",
            },
        },
    )

    assert answer_response.status_code == 200
    body = answer_response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    stages = {event["stage"]: event for event in body["teaching_trace"]}
    kt_diagnosis = expert["kt_diagnosis"]
    attribution = expert["attribution_evidence"]
    assembled = expert["assembled_context"]
    rag_sources = expert["rag_sources"]
    plan_metadata = stages["plan"]["metadata"]

    assert body["state_summary"]["intent"] == "answer_submission"
    assert body["state_summary"]["progress_version"] == 2
    assert "判定为不正确" in body["response"]

    assert kt_diagnosis["prediction_probability"] == 0.2
    assert kt_diagnosis["weak_concepts"][0]["concept_id"] == canonical_concept_id
    assert kt_diagnosis["forgetting_risks"][0]["concept_id"] == canonical_concept_id
    assert assembled["authoritative_kt_facts"]["prediction_probability"] == 0.2
    assert assembled["authoritative_kt_facts"]["weak_concepts"] == (
        kt_diagnosis["weak_concepts"]
    )

    assert attribution["evidence_status"] == "complete"
    assert attribution["evidence_source"] == "offline"
    assert attribution["partial_evidence"] is False
    assert attribution["prediction_probability"] == kt_diagnosis["prediction_probability"]
    assert attribution["target_question_id"] == canonical_question_id
    assert attribution["target_concept_id"] == canonical_concept_id
    assert attribution["target_assist2017_question_id"] == 3
    assert attribution["target_assist2017_concept_id"] == 2
    assert attribution["raw_model_target"]["sample_id"] == "fixture-s1-t2-q3"
    assert attribution["raw_model_target"]["canonical_question_id"] == canonical_question_id
    assert attribution["mapped_teaching_content"]["question_id"] == canonical_question_id
    assert attribution["mapped_teaching_content"]["concept_id"] == canonical_concept_id
    assert attribution["scorer"]["name"] == "dgekt_offline_path_scorer"
    assert attribution["scorer"]["run_id"] == "dgekt-fixture-run-20260709"
    assert attribution["top_paths"][0]["path_id"] == "path-fixture-history-q3"
    assert attribution["top_paths"][0]["target_question_id"] == canonical_question_id
    assert attribution["top_paths"][0]["target_concept_id"] == canonical_concept_id
    assert attribution["top_paths"][0]["partial_evidence"] is False
    assert attribution["key_history"][0]["target_question_id"] == canonical_question_id
    assert attribution["key_history"][0]["target_concept_id"] == canonical_concept_id
    assert attribution["path_ablation"][0]["impact"] == 0.16
    assert attribution["evidence_gaps"] == []

    assert any(source["question_id"] == canonical_question_id for source in rag_sources)
    assert any(source["concept_id"] == canonical_concept_id for source in rag_sources)
    assert any(source["assist2017_question_id"] == 3 for source in rag_sources)
    assert any(
        asset["question_id"] == canonical_question_id
        for asset in assembled["normalized_context"]["knowledge_resource"]
    )
    assert any(
        asset["concept_id"] == canonical_concept_id
        for asset in assembled["normalized_context"]["knowledge_resource"]
    )

    diagnose_metadata = stages["diagnose"]["metadata"]
    attribution_chain = diagnose_metadata["attribution_chain"]
    assert diagnose_metadata["prediction_facts"]["prediction_probability"] == 0.2
    assert attribution_chain["raw_model_target"]["target_question_id"] == 3
    assert attribution_chain["raw_model_target"]["canonical_question_id"] == canonical_question_id
    assert attribution_chain["mapped_teaching_content"]["question_id"] == canonical_question_id
    assert attribution_chain["attribution_evidence"]["evidence_status"] == "complete"
    assert attribution_chain["attribution_evidence"]["scorer"]["name"] == (
        "dgekt_offline_path_scorer"
    )
    assert attribution_chain["attribution_evidence"]["weak_concept_hit_count"] == 0
    assert plan_metadata["mistake_diagnosis"]["concept"]["concept_id"] == canonical_concept_id
    assert any(
        target["concept_id"] == canonical_concept_id
        for target in plan_metadata["selected_canonical_targets"]
    )
    assert any(
        source["question_id"] == canonical_question_id
        for source in plan_metadata["planner_evidence"]["rag_sources"]
    )


def test_v16_next_step_target_uses_same_offline_evidence_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient
    from backend.app.api import events as events_api
    from backend.app.main import create_app

    checkpoint, dataset_dir, q_matrix = write_dgekt_fraction_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        checkpoint_id="dgekt-assist2017-fixture-epoch26",
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
        offline_evidence_dir=str(DGEKT_OFFLINE_EVIDENCE_FIXTURE),
    )
    student_id = "student-dgekt-offline-fixture"
    store = InMemoryProgressStore()
    store.save(
        KTLearningProgress(
            student_id=student_id,
            recent_events=[
                LearningEvent(
                    session_id="session-v16-next-step-offline",
                    student_id=student_id,
                    type="answer_submitted",
                    payload={
                        "question_id": "q_frac_001",
                        "concept_id": "c_fraction_addition",
                        "concept_name": "异分母分数加法",
                        "assist2017_question_id": 3,
                        "assist2017_concept_id": 2,
                        "is_correct": False,
                    },
                )
            ],
        )
    )
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            kt_engine=engine,
            store=store,
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-v16-next-step-offline",
            "student_id": student_id,
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {
                "question_id": "q_frac_001",
                "preferred_concept_id": "c_fraction_addition",
                "preferred_teaching_type": "procedure",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    attribution = expert["attribution_evidence"]
    diagnose_event = next(event for event in body["teaching_trace"] if event["stage"] == "diagnose")

    assert body["state_summary"]["intent"] == "next_step_advice"
    assert body["recommended_questions"]
    assert attribution["evidence_status"] == "complete"
    assert attribution["evidence_source"] == "offline"
    assert attribution["target_question_id"] == "q_frac_001"
    assert attribution["mapped_teaching_content"]["concept_id"] == "c_fraction_addition"
    assert attribution["scorer"]["matching_method"] == "student_target_exact"
    assert diagnose_event["metadata"]["attribution_chain"]["attribution_evidence"][
        "evidence_status"
    ] == "complete"


def test_v16_offline_evidence_gap_reaches_api_trace_without_overwriting_kt_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient
    from backend.app.api import events as events_api
    from backend.app.main import create_app

    checkpoint, dataset_dir, q_matrix = write_dgekt_fraction_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        checkpoint_id="dgekt-assist2017-fixture-epoch26",
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
        offline_evidence_dir=str(tmp_path / "missing-offline-evidence"),
    )
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            kt_engine=engine,
            store=InMemoryProgressStore(),
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-v16-gap-api",
            "student_id": "student-dgekt-offline-fixture",
            "type": "answer_submitted",
            "message": "我选 1/6",
            "payload": {
                "question_id": "q_frac_001",
                "answer": "1/6",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    attribution = expert["attribution_evidence"]
    assembled = expert["assembled_context"]
    gap = attribution["evidence_gaps"][0]

    assert attribution["evidence_status"] == "unavailable"
    assert attribution["evidence_source"] == "offline"
    assert attribution["partial_evidence"] is True
    assert attribution["top_paths"][0]["partial_evidence"] is True
    assert attribution["top_paths"][0]["offline_evidence_status"] == "unavailable"
    assert gap["category"] == "missing_artifact"
    assert expert["kt_diagnosis"]["prediction_probability"] == 0.2
    assert expert["kt_diagnosis"]["weak_concepts"][0]["concept_id"] == "c_fraction_addition"
    assert assembled["authoritative_kt_facts"]["prediction_probability"] == 0.2
    assert any(
        context_gap["gap_type"] == "missing_artifact"
        and context_gap["evidence_status"] == "unavailable"
        and context_gap["evidence_source"] == "offline"
        for context_gap in assembled["evidence_gaps"]
    )
    assert "判定为不正确" in body["response"]


def test_dgekt_mapping_error_returns_readable_api_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient
    from backend.app.api import events as events_api
    from backend.app.main import create_app

    checkpoint, dataset_dir, q_matrix = write_dgekt_fixture_files(tmp_path)
    patch_fake_dgekt_runtime(monkeypatch, checkpoint)
    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=str(checkpoint),
        dataset_dir=str(dataset_dir),
        q_matrix_path=str(q_matrix),
    )
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            kt_engine=engine,
            store=InMemoryProgressStore(),
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-v12-dgekt-error",
            "student_id": "student-v12-dgekt-error",
            "type": "answer_submitted",
            "message": "提交无法映射的 DGEKT 题目",
            "payload": {
                "question_id": "q_mem_001",
                "answer": "42",
                "assist2017_question_id": 1,
                "assist2017_concept_id": 2,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    error_record = body["state_summary"]["error_records"][0]
    diagnose_event = next(event for event in body["teaching_trace"] if event["stage"] == "diagnose")
    assert error_record["category"] == "missing_mapping"
    assert error_record["code"] == "missing_mapping"
    assert "DGEKT 映射失败" in error_record["message"]
    assert "inconsistent with Q-matrix" in error_record["message"]
    assert diagnose_event["metadata"]["failure_stage"] == "diagnose"
    assert diagnose_event["metadata"]["error_records"][0]["category"] == "missing_mapping"
    assert body["teaching_trace_summary"]["expert_evidence"]["error_records"][0]["category"] == (
        "missing_mapping"
    )


@pytest.mark.skipif(
    os.getenv("MATHTUTOR_RUN_DGEKT_SMOKE") != "1",
    reason="Set MATHTUTOR_RUN_DGEKT_SMOKE=1 to load the local DGEKT checkpoint.",
)
def test_dgekt_real_checkpoint_smoke() -> None:
    checkpoint = os.getenv(
        "MATHTUTOR_DGEKT_CHECKPOINT_PATH",
        "/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/"
        "DGEKT原版-自注意力机制-master_副本/KnowledgeTracing/model/runs/"
        "20260707_222733/save2017model.pkl",
    )
    dataset_dir = os.getenv(
        "MATHTUTOR_DGEKT_DATASET_DIR",
        "/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/"
        "DGEKT原版-自注意力机制-master_副本/Dataset/assist2017",
    )
    q_matrix = os.getenv(
        "MATHTUTOR_DGEKT_Q_MATRIX_PATH",
        "/Users/lqc/Downloads/LDGEKT_副本/90_源码与原始工程/"
        "DGEKT原版-自注意力机制-master_副本/Dataset/H/2017.csv",
    )

    engine = DGEKTStateEngine(
        dataset="assist2017",
        checkpoint_path=checkpoint,
        dataset_dir=dataset_dir,
        q_matrix_path=q_matrix,
    )

    assert engine.diagnostics["epoch"] == 26
    assert engine.diagnostics["model_eval"] is True
    assert engine.runtime.model.training is False
