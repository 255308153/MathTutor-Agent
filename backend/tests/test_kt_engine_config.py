import os
from pathlib import Path
from types import SimpleNamespace

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
    checkpoint = tmp_path / "save2017model.pkl"
    checkpoint.write_bytes(b"not-a-real-checkpoint")
    q_matrix = tmp_path / "2017.csv"
    q_matrix.write_text("1,0,1\n", encoding="utf-8")
    dataset_dir = tmp_path / "assist2017"
    dataset_dir.mkdir()
    (dataset_dir / "assist2017_pid_train.csv").write_text("train\n", encoding="utf-8")
    (dataset_dir / "assist2017_pid_test.csv").write_text("test\n", encoding="utf-8")

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
    checkpoint = tmp_path / "save2017model.pkl"
    checkpoint.write_bytes(b"not-a-real-checkpoint")
    q_matrix = tmp_path / "2017.csv"
    q_matrix.write_text("1,0,1\n", encoding="utf-8")
    dataset_dir = tmp_path / "assist2017"
    dataset_dir.mkdir()
    (dataset_dir / "assist2017_pid_train.csv").write_text("train\n", encoding="utf-8")
    (dataset_dir / "assist2017_pid_test.csv").write_text("test\n", encoding="utf-8")

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
    checkpoint = tmp_path / "save2017model.pkl"
    checkpoint.write_bytes(b"not-a-real-checkpoint")
    q_matrix = tmp_path / "2017.csv"
    q_matrix.write_text("1,0,1\n", encoding="utf-8")
    dataset_dir = tmp_path / "assist2017"
    dataset_dir.mkdir()
    (dataset_dir / "assist2017_pid_train.csv").write_text("train\n", encoding="utf-8")
    (dataset_dir / "assist2017_pid_test.csv").write_text("test\n", encoding="utf-8")

    def fake_load_runtime(self: DGEKTStateEngine, *, device: str) -> DGEKTRuntime:
        return DGEKTRuntime(
            model=SimpleNamespace(training=False),
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
