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
)
from backend.app.kt.factory import create_kt_engine
from backend.app.kt.mock_engine import MockKTStateEngine
from backend.app.schemas.learning import AttributionEvidence, KTDiagnosis, KTLearningProgress, LearningEvent
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.storage.progress_store import InMemoryProgressStore


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
    q_matrix.write_text("1,0\n0,1\n", encoding="utf-8")
    dataset_dir = tmp_path / "assist2017"
    dataset_dir.mkdir()
    (dataset_dir / "assist2017_pid_train.csv").write_text("train\n", encoding="utf-8")
    (dataset_dir / "assist2017_pid_test.csv").write_text("test\n", encoding="utf-8")
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
    assert dgekt_evidence.key_history[0]["assist2017_question_id"] == 1
    assert dgekt_evidence.prediction_probability == 0.2
    assert dgekt_diagnosis.prediction_probability == 0.2


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
    assert body["state_summary"]["intent"] == "answer_submission"
    assert body["teaching_trace"][1]["stage"] == "diagnose"
    assert body["teaching_trace"][1]["metadata"]["kt_engine"] == "dgekt"
    assert body["teaching_trace"][1]["metadata"]["prediction_probability"] == 0.2
    attribution = body["teaching_trace_summary"]["expert_evidence"]["attribution_evidence"]
    assert attribution["prediction_probability"] == 0.2
    assert attribution["top_paths"][0]["partial_evidence"] is True
    assert attribution["top_paths"][0]["evidence_status"] == "partial"
    assert attribution["key_history"][0]["assist2017_question_id"] == 1
    assert "partial_evidence" not in body["response"]
    assert "top_paths" not in body["response"]
    assert "DGEKT inference input built" in body["teaching_trace"][1]["metadata"]["evidence"][2]
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
