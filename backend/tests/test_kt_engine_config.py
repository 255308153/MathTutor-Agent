from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.core.config import MathTutorSettings
from backend.app.kt.dgekt_engine import DGEKTConfigurationError, DGEKTStateEngine
from backend.app.kt.factory import create_kt_engine
from backend.app.kt.mock_engine import MockKTStateEngine


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
