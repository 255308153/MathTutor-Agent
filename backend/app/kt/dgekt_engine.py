from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .engine import KTStateEngine
from ..schemas.learning import AttributionEvidence, KTDiagnosis, KTLearningProgress, LearningEvent


SUPPORTED_DATASETS = {"assist2017"}


class DGEKTConfigurationError(RuntimeError):
    """Raised when the real DGEKT engine is requested but local files are missing."""


@dataclass(frozen=True)
class DGEKTPaths:
    checkpoint_path: Path
    dataset_dir: Path
    q_matrix_path: Path


class DGEKTStateEngine(KTStateEngine):
    """Safety-checked adapter boundary for the real ASSIST2017 DGEKT engine.

    Issue #13 only establishes configuration validation and the KTStateEngine seam.
    Checkpoint loading and real inference are implemented in the following slices.
    """

    def __init__(
        self,
        *,
        dataset: str,
        checkpoint_path: str,
        dataset_dir: str,
        q_matrix_path: str,
    ) -> None:
        self.dataset = dataset
        self.paths = self.validate_configuration(
            dataset=dataset,
            checkpoint_path=checkpoint_path,
            dataset_dir=dataset_dir,
            q_matrix_path=q_matrix_path,
        )

    @classmethod
    def validate_configuration(
        cls,
        *,
        dataset: str,
        checkpoint_path: str,
        dataset_dir: str,
        q_matrix_path: str,
    ) -> DGEKTPaths:
        if dataset not in SUPPORTED_DATASETS:
            supported = ", ".join(sorted(SUPPORTED_DATASETS))
            raise DGEKTConfigurationError(
                f"Unsupported DGEKT dataset '{dataset}'. Set MATHTUTOR_DGEKT_DATASET "
                f"to one of: {supported}."
            )

        checkpoint = cls._require_file(
            value=checkpoint_path,
            env_name="MATHTUTOR_DGEKT_CHECKPOINT_PATH",
            description="ASSIST2017 DGEKT checkpoint (.pkl)",
        )
        dataset_root = cls._require_dir(
            value=dataset_dir,
            env_name="MATHTUTOR_DGEKT_DATASET_DIR",
            description="ASSIST2017 dataset directory",
        )
        q_matrix = cls._require_file(
            value=q_matrix_path,
            env_name="MATHTUTOR_DGEKT_Q_MATRIX_PATH",
            description="DGEKT Q-matrix / incidence matrix file",
        )

        for filename in ("assist2017_pid_train.csv", "assist2017_pid_test.csv"):
            cls._require_file(
                value=str(dataset_root / filename),
                env_name="MATHTUTOR_DGEKT_DATASET_DIR",
                description=f"ASSIST2017 data file {filename}",
            )

        return DGEKTPaths(
            checkpoint_path=checkpoint,
            dataset_dir=dataset_root,
            q_matrix_path=q_matrix,
        )

    @staticmethod
    def _require_file(*, value: str, env_name: str, description: str) -> Path:
        if not value:
            raise DGEKTConfigurationError(
                f"Missing {description}. Set {env_name} to the local file path."
            )
        path = Path(value).expanduser()
        if not path.is_file():
            raise DGEKTConfigurationError(
                f"Missing {description}: {path}. Verify the file exists and update {env_name}."
            )
        return path

    @staticmethod
    def _require_dir(*, value: str, env_name: str, description: str) -> Path:
        if not value:
            raise DGEKTConfigurationError(
                f"Missing {description}. Set {env_name} to the local directory path."
            )
        path = Path(value).expanduser()
        if not path.is_dir():
            raise DGEKTConfigurationError(
                f"Missing {description}: {path}. Verify the directory exists and update {env_name}."
            )
        return path

    def update_from_event(
        self,
        progress: KTLearningProgress,
        event: LearningEvent,
    ) -> KTLearningProgress:
        raise NotImplementedError("DGEKT checkpoint inference is implemented after issue #13.")

    def diagnose(
        self,
        progress: KTLearningProgress,
        target_question_id: str | None = None,
    ) -> KTDiagnosis:
        raise NotImplementedError("DGEKT checkpoint inference is implemented after issue #13.")

    def explain_prediction(
        self,
        progress: KTLearningProgress,
        target_question_id: str,
    ) -> AttributionEvidence:
        raise NotImplementedError("DGEKT attribution inference is implemented after issue #13.")
