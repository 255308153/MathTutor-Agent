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


class DGEKTMappingError(ValueError):
    """Raised when MathTutor events cannot be mapped into ASSIST2017 ids."""


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


@dataclass(frozen=True)
class DGEKTInferenceInput:
    tensor: Any
    question_ids: list[int]
    answers: list[int]
    concept_ids: list[int]
    mathtutor_concepts: list[dict[str, Any]]
    source_event_count: int

    def summary(self) -> dict[str, Any]:
        return {
            "sequence_length": len(self.question_ids),
            "question_ids": self.question_ids,
            "answers": self.answers,
            "concept_ids": self.concept_ids,
            "mathtutor_concepts": self.mathtutor_concepts,
            "source_event_count": self.source_event_count,
        }


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
        self.question_concept_map = self._load_question_concept_map()
        self.last_inference_input: DGEKTInferenceInput | None = None

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
        diagnostics = dict(self.metadata)
        if self.last_inference_input:
            diagnostics["last_inference_input"] = self.last_inference_input.summary()
        return diagnostics

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

    def _load_question_concept_map(self) -> dict[int, list[int]]:
        try:
            import pandas as pd
        except ImportError as exc:
            raise DGEKTCheckpointError(
                "DGEKT input mapping requires pandas to read the Q-matrix."
            ) from exc

        q_matrix = pd.read_csv(self.paths.q_matrix_path, header=None)
        mapping: dict[int, list[int]] = {}
        for row_index, row in q_matrix.iterrows():
            concepts = [
                int(column_index) + 1
                for column_index, value in enumerate(row.tolist())
                if int(value) == 1
            ]
            mapping[int(row_index) + 1] = concepts
        return mapping

    def build_inference_input(self, progress: KTLearningProgress) -> DGEKTInferenceInput | None:
        answer_events = [
            event
            for event in progress.recent_events
            if event.type == "answer_submitted" and event.payload.get("is_correct") is not None
        ][-ASSIST2017_MAX_STEP:]
        if not answer_events:
            self.last_inference_input = None
            return None

        question_ids: list[int] = []
        answers: list[int] = []
        concept_ids: list[int] = []
        mathtutor_concepts: list[dict[str, Any]] = []
        for event in answer_events:
            question_id = self._extract_assist2017_question_id(event)
            answer = 1 if event.payload.get("is_correct") is True else 0
            concept_id = self._resolve_assist2017_concept_id(event, question_id)
            question_ids.append(question_id)
            answers.append(answer)
            concept_ids.append(concept_id)
            mathtutor_concepts.append(
                {
                    "concept_id": event.payload.get("concept_id"),
                    "concept_name": event.payload.get("concept_name"),
                    "teaching_type": event.payload.get("teaching_type"),
                    "assist2017_concept_id": concept_id,
                }
            )

        inference_input = DGEKTInferenceInput(
            tensor=self._one_hot_sequence(question_ids=question_ids, answers=answers),
            question_ids=question_ids,
            answers=answers,
            concept_ids=concept_ids,
            mathtutor_concepts=mathtutor_concepts,
            source_event_count=len(answer_events),
        )
        self.last_inference_input = inference_input
        return inference_input

    def _extract_assist2017_question_id(self, event: LearningEvent) -> int:
        raw_question_id = (
            event.payload.get("assist2017_question_id")
            or event.payload.get("dgekt_question_id")
            or event.payload.get("question_id")
        )
        if raw_question_id is None:
            raise DGEKTMappingError(
                "Missing ASSIST2017 question mapping. Add assist2017_question_id or "
                "dgekt_question_id to the LearningEvent payload."
            )
        question_id = self._parse_assist2017_id(raw_question_id, field_name="question_id")
        if question_id < 1 or question_id > ASSIST2017_QUESTION_COUNT:
            raise DGEKTMappingError(
                f"ASSIST2017 question_id {question_id} is out of range 1.."
                f"{ASSIST2017_QUESTION_COUNT}."
            )
        if question_id not in self.question_concept_map:
            raise DGEKTMappingError(
                f"ASSIST2017 question_id {question_id} is missing from the configured Q-matrix."
            )
        if not self.question_concept_map[question_id]:
            raise DGEKTMappingError(
                f"ASSIST2017 question_id {question_id} has no concept in the configured Q-matrix."
            )
        return question_id

    def _resolve_assist2017_concept_id(self, event: LearningEvent, question_id: int) -> int:
        mapped_concepts = self.question_concept_map[question_id]
        raw_concept_id = event.payload.get("assist2017_concept_id") or event.payload.get("dgekt_concept_id")
        if raw_concept_id is None:
            return mapped_concepts[0]
        concept_id = self._parse_assist2017_id(raw_concept_id, field_name="concept_id")
        if concept_id not in mapped_concepts:
            raise DGEKTMappingError(
                f"ASSIST2017 concept_id {concept_id} is inconsistent with Q-matrix mapping "
                f"for question_id {question_id}; expected one of {mapped_concepts}."
            )
        return concept_id

    def _parse_assist2017_id(self, raw_value: Any, *, field_name: str) -> int:
        if isinstance(raw_value, int):
            return raw_value
        value = str(raw_value)
        if value.startswith("assist2017:"):
            value = value.split(":", 1)[1]
        if not value.isdigit():
            raise DGEKTMappingError(
                f"Cannot map MathTutor {field_name} '{raw_value}' to ASSIST2017. "
                f"Use an integer id or assist2017:<id>."
            )
        return int(value)

    def _one_hot_sequence(self, *, question_ids: list[int], answers: list[int]) -> Any:
        try:
            import torch
        except ImportError as exc:
            raise DGEKTCheckpointError("DGEKT input tensor construction requires torch.") from exc

        tensor = torch.zeros(
            1,
            ASSIST2017_MAX_STEP,
            2 * ASSIST2017_QUESTION_COUNT,
            device=self.runtime.device,
        )
        start = max(0, ASSIST2017_MAX_STEP - len(question_ids))
        for offset, (question_id, answer) in enumerate(zip(question_ids, answers)):
            column = question_id - 1 if answer == 1 else ASSIST2017_QUESTION_COUNT + question_id - 1
            tensor[0, start + offset, column] = 1.0
        return tensor

    def _prediction_probability(
        self,
        inference_input: DGEKTInferenceInput,
        target_question_id: str | None,
    ) -> float:
        try:
            import torch
        except ImportError as exc:
            raise DGEKTCheckpointError("DGEKT prediction requires torch.") from exc

        target_assist2017_id = self._target_assist2017_question_id(
            inference_input=inference_input,
            target_question_id=target_question_id,
        )
        sequence_index = ASSIST2017_MAX_STEP - 1
        with torch.no_grad():
            output = self.runtime.model(inference_input.tensor)
            if isinstance(output, tuple) and len(output) == 2:
                output = output[0]
            logit_ensemble = output[2]
            probability = torch.sigmoid(logit_ensemble)[0, sequence_index, target_assist2017_id - 1]
        return round(float(probability.detach().cpu().item()), 6)

    def _target_assist2017_question_id(
        self,
        *,
        inference_input: DGEKTInferenceInput,
        target_question_id: str | None,
    ) -> int:
        if target_question_id:
            try:
                return self._parse_assist2017_id(target_question_id, field_name="target_question_id")
            except DGEKTMappingError:
                pass
        return inference_input.question_ids[-1]

    def _prediction_weak_concepts(
        self,
        inference_input: DGEKTInferenceInput,
        prediction_probability: float,
    ) -> list[dict[str, Any]]:
        concept = inference_input.mathtutor_concepts[-1] if inference_input.mathtutor_concepts else {}
        concept_id = concept.get("concept_id") or f"assist2017_concept:{inference_input.concept_ids[-1]}"
        concept_name = concept.get("concept_name") or f"ASSIST2017 concept {inference_input.concept_ids[-1]}"
        mastery = prediction_probability
        if mastery >= 0.6:
            return []
        return [
            {
                "concept_id": concept_id,
                "concept_name": concept_name,
                "mastery": mastery,
                "prediction_probability": prediction_probability,
                "assist2017_concept_id": inference_input.concept_ids[-1],
                "reason": "DGEKT prediction probability below mastery threshold",
            }
        ]

    def _prediction_forgetting_risks(
        self,
        inference_input: DGEKTInferenceInput,
        prediction_probability: float,
    ) -> list[dict[str, Any]]:
        risk = round(1.0 - prediction_probability, 6)
        if risk < 0.4:
            return []
        concept = inference_input.mathtutor_concepts[-1] if inference_input.mathtutor_concepts else {}
        return [
            {
                "concept_id": concept.get("concept_id")
                or f"assist2017_concept:{inference_input.concept_ids[-1]}",
                "concept_name": concept.get("concept_name")
                or f"ASSIST2017 concept {inference_input.concept_ids[-1]}",
                "forgetting_risk": risk,
                "prediction_probability": prediction_probability,
                "risk_source": "dgekt_prediction_proxy",
            }
        ]

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
        inference_input = self.build_inference_input(progress)
        prediction_probability = (
            self._prediction_probability(inference_input, target_question_id)
            if inference_input
            else None
        )
        evidence = [
            "DGEKT checkpoint loaded and model is in eval mode.",
            (
                f"checkpoint epoch={self.metadata['epoch']} "
                f"auc={self.metadata['auc']:.6f} acc={self.metadata['acc']:.6f}"
            ),
        ]
        if inference_input:
            evidence.append(
                "DGEKT inference input built from MathTutor recent answer history: "
                f"sequence_length={len(inference_input.question_ids)}."
            )
        else:
            evidence.append("No graded answer history available for DGEKT inference input yet.")
        weak_concepts = (
            self._prediction_weak_concepts(inference_input, prediction_probability)
            if inference_input and prediction_probability is not None
            else list(progress.weak_concepts)
        )
        forgetting_risks = (
            self._prediction_forgetting_risks(inference_input, prediction_probability)
            if inference_input and prediction_probability is not None
            else list(progress.forgetting_risks)
        )
        return KTDiagnosis(
            weak_concepts=weak_concepts,
            forgetting_risks=forgetting_risks,
            prediction_probability=prediction_probability,
            evidence=evidence,
            metadata={
                "engine_name": self.engine_name,
                "model_provenance": dict(self.metadata),
                "prediction_facts": {
                    "prediction_probability": prediction_probability,
                    "weak_concepts": weak_concepts,
                    "forgetting_risks": forgetting_risks,
                },
                "inference_input": inference_input.summary() if inference_input else None,
            },
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
