from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from .engine import KTStateEngine
from ..schemas.learning import AttributionEvidence, KTDiagnosis, KTLearningProgress, LearningEvent


SUPPORTED_DATASETS = {"assist2017"}
ASSIST2017_QUESTION_COUNT = 3162
ASSIST2017_HIDDEN_DIM = 128
ASSIST2017_LAYERS = 1
ASSIST2017_MAX_STEP = 50


class DGEKTConfigurationError(RuntimeError):
    """Raised when the real DGEKT engine is requested but local files are missing."""


class DGEKTCheckpointError(RuntimeError):
    """Raised when the configured checkpoint cannot be loaded as a DGEKT runtime."""


@dataclass(frozen=True)
class DGEKTPaths:
    checkpoint_path: Path
    dataset_dir: Path
    q_matrix_path: Path


@dataclass(frozen=True)
class DGEKTRuntime:
    model: Any
    device: str
    metadata: dict[str, Any]


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
        device: str = "cpu",
    ) -> None:
        self.dataset = dataset
        self.paths = self.validate_configuration(
            dataset=dataset,
            checkpoint_path=checkpoint_path,
            dataset_dir=dataset_dir,
            q_matrix_path=q_matrix_path,
        )
        self.runtime = self._load_runtime(device=device)
        self.engine_name = "dgekt"
        self.metadata = self.runtime.metadata

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

    @property
    def diagnostics(self) -> dict[str, Any]:
        return dict(self.metadata)

    def _load_runtime(self, *, device: str) -> DGEKTRuntime:
        try:
            import torch
        except ImportError as exc:
            raise DGEKTCheckpointError(
                "PyTorch is required when MATHTUTOR_KT_ENGINE=dgekt. "
                "Install torch or switch MATHTUTOR_KT_ENGINE back to mock."
            ) from exc

        checkpoint = self._load_checkpoint(torch=torch)
        self._validate_checkpoint_dict(checkpoint)
        model = self._build_model(device=device)
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
        model.eval()

        metadata = {
            "engine_name": "dgekt",
            "dataset": self.dataset,
            "checkpoint_path": str(self.paths.checkpoint_path),
            "epoch": int(checkpoint["epoch"]),
            "auc": float(checkpoint["auc"]),
            "acc": float(checkpoint["acc"]),
            "device": device,
            "model_eval": not model.training,
            "optimizer_state_available": "optimizer_state_dict" in checkpoint,
        }
        return DGEKTRuntime(model=model, device=device, metadata=metadata)

    def _load_checkpoint(self, *, torch: Any) -> dict[str, Any]:
        try:
            checkpoint = torch.load(
                self.paths.checkpoint_path,
                map_location="cpu",
                weights_only=False,
            )
        except Exception as exc:
            raise DGEKTCheckpointError(
                f"Failed to load DGEKT checkpoint at {self.paths.checkpoint_path}: {exc}"
            ) from exc
        if not isinstance(checkpoint, dict):
            raise DGEKTCheckpointError(
                f"DGEKT checkpoint at {self.paths.checkpoint_path} must be a dict, "
                f"got {type(checkpoint).__name__}."
            )
        return checkpoint

    def _validate_checkpoint_dict(self, checkpoint: dict[str, Any]) -> None:
        required = {"epoch", "model_state_dict", "optimizer_state_dict", "auc", "acc"}
        missing = sorted(required - set(checkpoint))
        if missing:
            raise DGEKTCheckpointError(
                "DGEKT checkpoint is missing required key(s): "
                + ", ".join(missing)
                + ". Expected epoch, model_state_dict, optimizer_state_dict, auc, acc."
            )
        state_dict = checkpoint["model_state_dict"]
        if not hasattr(state_dict, "keys"):
            raise DGEKTCheckpointError("DGEKT checkpoint model_state_dict must be a state dict.")

    def _build_model(self, *, device: str) -> Any:
        try:
            import numpy as np
            import pandas as pd
            import scipy.sparse as sp
            import torch
        except ImportError as exc:
            raise DGEKTCheckpointError(
                "DGEKT model loading requires numpy, pandas, scipy, and torch. "
                "Install the original DGEKT runtime dependencies or switch to mock."
            ) from exc

        project_root = self.paths.dataset_dir.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        try:
            from KnowledgeTracing.Constant import Constants as C
            from KnowledgeTracing.model.Model import DKT
        except Exception as exc:
            raise DGEKTCheckpointError(
                "Failed to import original KnowledgeTracing DKT model. "
                f"Expected project root on sys.path: {project_root}. Original error: {exc}"
            ) from exc

        C.DATASET = self.dataset
        C.NUM_OF_QUESTIONS = ASSIST2017_QUESTION_COUNT
        C.H = "2017"
        C.MAX_STEP = ASSIST2017_MAX_STEP
        C.HIDDEN = ASSIST2017_HIDDEN_DIM
        C.LAYERS = ASSIST2017_LAYERS

        q_matrix = pd.read_csv(self.paths.q_matrix_path, header=None)
        graph = self._generate_hypergraph(q_matrix, np=np, sp=sp, torch=torch).to(device)
        adj_out, adj_in = self._generate_transition_adjacency(np=np, sp=sp, torch=torch)
        model = DKT(ASSIST2017_HIDDEN_DIM, ASSIST2017_LAYERS, graph, adj_out.to(device), adj_in.to(device))
        return model.to(device)

    def _generate_hypergraph(self, h_matrix: Any, *, np: Any, sp: Any, torch: Any) -> Any:
        h = np.asarray(h_matrix)
        edge_count = h.shape[1]
        weights = np.ones(edge_count)
        node_degrees = np.sum(h * weights, axis=1)
        edge_degrees = np.sum(h, axis=0)
        inv_edge_degrees = np.asmatrix(np.diag(np.power(edge_degrees, -1.0)))
        inv_sqrt_node_degrees = np.asmatrix(np.diag(np.power(node_degrees, -0.5)))
        weight_matrix = np.asmatrix(np.diag(weights))
        h = np.asmatrix(h)
        graph = inv_sqrt_node_degrees * h * weight_matrix * inv_edge_degrees * h.T * inv_sqrt_node_degrees
        return self._sparse_matrix_to_torch(sp.coo_matrix(graph), np=np, torch=torch)

    def _generate_transition_adjacency(self, *, np: Any, sp: Any, torch: Any) -> tuple[Any, Any]:
        question_count = ASSIST2017_QUESTION_COUNT
        adjacency_out = np.zeros((2 * question_count, 2 * question_count), dtype=np.float32)
        train_path = self.paths.dataset_dir / "assist2017_pid_train.csv"
        with train_path.open("r", encoding="UTF-8-sig") as train_file:
            rows = iter(train_file)
            for length_line, questions_line, _unused, answers_line in zip(rows, rows, rows, rows):
                sequence_length = int(length_line.strip().strip(","))
                questions = np.array(questions_line.strip().strip(",").split(",")).astype(int)
                answers = np.array(answers_line.strip().strip(",").split(",")).astype(int)
                if sequence_length <= 1:
                    continue
                for index in range(sequence_length):
                    if answers[index] == 0:
                        questions[index] += question_count
                for index in range(sequence_length - 1):
                    adjacency_out[questions[index] - 1][questions[index + 1] - 1] += 1

        adjacency_in = adjacency_out.T
        adjacency_out = self._normalize(adjacency_out + sp.eye(adjacency_out.shape[0]))
        adjacency_in = self._normalize(adjacency_in + sp.eye(adjacency_in.shape[0]))
        return (
            self._sparse_matrix_to_torch(sp.coo_matrix(adjacency_out), np=np, torch=torch),
            self._sparse_matrix_to_torch(sp.coo_matrix(adjacency_in), np=np, torch=torch),
        )

    def _normalize(self, matrix: Any) -> Any:
        import numpy as np
        import scipy.sparse as sp

        row_sum = np.array(matrix.sum(1))
        inverse = np.power(row_sum, -1).flatten()
        inverse[np.isinf(inverse)] = 0.0
        inverse_matrix = sp.diags(inverse)
        return inverse_matrix.dot(matrix)

    def _sparse_matrix_to_torch(self, sparse_matrix: Any, *, np: Any, torch: Any) -> Any:
        sparse_matrix = sparse_matrix.tocoo().astype(np.float32)
        indices = torch.from_numpy(np.vstack((sparse_matrix.row, sparse_matrix.col)).astype(np.int64))
        values = torch.from_numpy(sparse_matrix.data)
        shape = torch.Size(sparse_matrix.shape)
        return torch.sparse_coo_tensor(indices, values, shape)

    def update_from_event(
        self,
        progress: KTLearningProgress,
        event: LearningEvent,
    ) -> KTLearningProgress:
        progress.current_session_id = event.session_id
        progress.recent_events.append(event)
        progress.recent_events = progress.recent_events[-ASSIST2017_MAX_STEP:]
        progress.version += 1
        return progress

    def diagnose(
        self,
        progress: KTLearningProgress,
        target_question_id: str | None = None,
    ) -> KTDiagnosis:
        evidence = [
            "DGEKT checkpoint loaded and model is in eval mode.",
            (
                f"checkpoint epoch={self.metadata['epoch']} "
                f"auc={self.metadata['auc']:.6f} acc={self.metadata['acc']:.6f}"
            ),
        ]
        return KTDiagnosis(
            weak_concepts=list(progress.weak_concepts),
            forgetting_risks=list(progress.forgetting_risks),
            prediction_probability=None,
            evidence=evidence,
        )

    def explain_prediction(
        self,
        progress: KTLearningProgress,
        target_question_id: str,
    ) -> AttributionEvidence:
        key_history = [
            {
                "event_type": event.type,
                "question_id": event.payload.get("question_id"),
                "is_correct": event.payload.get("is_correct"),
            }
            for event in progress.recent_events[-5:]
        ]
        return AttributionEvidence(
            target_question_id=target_question_id,
            prediction_probability=None,
            top_paths=[
                {
                    "path_id": "dgekt-checkpoint-loaded",
                    "description": "ASSIST2017 DGEKT checkpoint loaded; attribution inference follows in #17.",
                    "weight": 1.0,
                    "engine": "dgekt",
                    "epoch": self.metadata["epoch"],
                }
            ],
            key_history=key_history,
            weak_concepts=list(progress.weak_concepts),
        )
