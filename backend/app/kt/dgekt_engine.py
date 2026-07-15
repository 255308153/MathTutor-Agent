from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from .engine import KTStateEngine
from .offline_evidence import DGEKTOfflineEvidenceAdapter
from ..mapping.xes3g5m_mapping import DEFAULT_MAPPING_PATH
from ..schemas.learning import AttributionEvidence, KTDiagnosis, KTLearningProgress, LearningEvent


SUPPORTED_DATASETS = {"xes3g5m"}
XES3G5M_QUESTION_COUNT = 3162
XES3G5M_HIDDEN_DIM = 128
XES3G5M_LAYERS = 1
XES3G5M_MAX_STEP = 50
DGEKT_ONLINE_SCORER_NAME = "dgekt_online_graph_proxy_scorer"
DGEKT_ONLINE_SCORER_VERSION = "v1.3-partial"
DGEKT_RELATION_SOURCE = "kc_routes_recent_history_proxy"
DGEKT_PARTIAL_ATTRIBUTION_REASON = (
    "Online MathTutor has the DGEKT prediction, recent XES3G5M sequence, and KC routes "
    "links, but does not yet run the original offline DGEKT explainability path scorer."
)


class DGEKTConfigurationError(RuntimeError):
    """Raised when the real DGEKT engine is requested but local files are missing."""


class DGEKTCheckpointError(RuntimeError):
    """Raised when the configured checkpoint cannot be loaded as a DGEKT runtime."""


class DGEKTMappingError(ValueError):
    """Raised when MathTutor events cannot be mapped into XES3G5M ids."""


class DGEKTUnsupportedTargetError(DGEKTMappingError):
    """Raised when an explicit DGEKT prediction target cannot be scored."""


@dataclass(frozen=True)
class DGEKTPaths:
    checkpoint_path: Path
    dataset_dir: Path
    kc_routes_path: Path


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
    """Safety-checked adapter boundary for the real XES3G5M DGEKT engine.

    Issue #13 only establishes configuration validation and the KTStateEngine seam.
    Checkpoint loading and real inference are implemented in the following slices.
    """

    def __init__(
        self,
        *,
        dataset: str,
        checkpoint_path: str,
        dataset_dir: str,
        kc_routes_path: str,
        checkpoint_id: str = "",
        offline_evidence_dir: str = "",
        canonical_mapping_path: str = "",
        device: str = "cpu",
    ) -> None:
        self.dataset = dataset
        self.paths = self.validate_configuration(
            dataset=dataset,
            checkpoint_path=checkpoint_path,
            dataset_dir=dataset_dir,
            kc_routes_path=kc_routes_path,
        )
        self.runtime = self._load_runtime(device=device)
        self.engine_name = "dgekt"
        self.metadata = self.runtime.metadata
        if checkpoint_id:
            self.metadata["checkpoint_id"] = checkpoint_id
        self.question_concept_map = self._load_question_concept_map()
        self.last_inference_input: DGEKTInferenceInput | None = None
        self.offline_evidence_adapter = (
            DGEKTOfflineEvidenceAdapter(
                offline_evidence_dir,
                canonical_mapping_path=canonical_mapping_path or DEFAULT_MAPPING_PATH,
            )
            if offline_evidence_dir
            else None
        )

    @classmethod
    def validate_configuration(
        cls,
        *,
        dataset: str,
        checkpoint_path: str,
        dataset_dir: str,
        kc_routes_path: str,
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
            description="XES3G5M DGEKT checkpoint (.pkl)",
        )
        dataset_root = cls._require_dir(
            value=dataset_dir,
            env_name="MATHTUTOR_DGEKT_DATASET_DIR",
            description="XES3G5M dataset directory",
        )
        kc_routes = cls._require_file(
            value=kc_routes_path,
            env_name="MATHTUTOR_DGEKT_Q_MATRIX_PATH",
            description="DGEKT KC routes / incidence matrix file",
        )

        for filename in ("xes3g5m_pid_train.csv", "xes3g5m_pid_test.csv"):
            cls._require_file(
                value=str(dataset_root / filename),
                env_name="MATHTUTOR_DGEKT_DATASET_DIR",
                description=f"XES3G5M data file {filename}",
            )

        return DGEKTPaths(
            checkpoint_path=checkpoint,
            dataset_dir=dataset_root,
            kc_routes_path=kc_routes,
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
        C.NUM_OF_QUESTIONS = XES3G5M_QUESTION_COUNT
        C.H = "2017"
        C.MAX_STEP = XES3G5M_MAX_STEP
        C.HIDDEN = XES3G5M_HIDDEN_DIM
        C.LAYERS = XES3G5M_LAYERS

        kc_routes = pd.read_csv(self.paths.kc_routes_path, header=None)
        graph = self._generate_hypergraph(kc_routes, np=np, sp=sp, torch=torch).to(device)
        adj_out, adj_in = self._generate_transition_adjacency(np=np, sp=sp, torch=torch)
        model = DKT(XES3G5M_HIDDEN_DIM, XES3G5M_LAYERS, graph, adj_out.to(device), adj_in.to(device))
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
        question_count = XES3G5M_QUESTION_COUNT
        adjacency_out = np.zeros((2 * question_count, 2 * question_count), dtype=np.float32)
        train_path = self.paths.dataset_dir / "xes3g5m_pid_train.csv"
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
                "DGEKT input mapping requires pandas to read the KC routes."
            ) from exc

        kc_routes = pd.read_csv(self.paths.kc_routes_path, header=None)
        mapping: dict[int, list[int]] = {}
        for row_index, row in kc_routes.iterrows():
            concepts = [
                int(column_index) + 1
                for column_index, value in enumerate(row.tolist())
                if int(value) == 1
            ]
            mapping[int(row_index) + 1] = concepts
        return mapping

    def build_inference_input(self, progress: KTLearningProgress) -> DGEKTInferenceInput | None:
        answer_events = self._graded_answer_events(progress)
        if not answer_events:
            self.last_inference_input = None
            return None

        question_ids: list[int] = []
        answers: list[int] = []
        concept_ids: list[int] = []
        mathtutor_concepts: list[dict[str, Any]] = []
        for event in answer_events:
            question_id = self._extract_xes3g5m_question_id(event)
            answer = 1 if event.payload.get("is_correct") is True else 0
            concept_id = self._resolve_xes3g5m_concept_id(event, question_id)
            question_ids.append(question_id)
            answers.append(answer)
            concept_ids.append(concept_id)
            mathtutor_concepts.append(
                {
                    "concept_id": event.payload.get("concept_id"),
                    "concept_name": event.payload.get("concept_name"),
                    "teaching_type": event.payload.get("teaching_type"),
                    "xes3g5m_concept_id": concept_id,
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

    def _graded_answer_events(self, progress: KTLearningProgress) -> list[LearningEvent]:
        return [
            event
            for event in progress.recent_events
            if event.type == "answer_submitted" and event.payload.get("is_correct") is not None
        ][-XES3G5M_MAX_STEP:]

    def _extract_xes3g5m_question_id(self, event: LearningEvent) -> int:
        raw_question_id = (
            event.payload.get("xes3g5m_question_id")
            or event.payload.get("dgekt_question_id")
            or event.payload.get("question_id")
        )
        if raw_question_id is None:
            raise DGEKTMappingError(
                "Missing XES3G5M question mapping. Add xes3g5m_question_id or "
                "dgekt_question_id to the LearningEvent payload."
            )
        question_id = self._parse_xes3g5m_id(raw_question_id, field_name="question_id")
        if question_id < 1 or question_id > XES3G5M_QUESTION_COUNT:
            raise DGEKTMappingError(
                f"XES3G5M question_id {question_id} is out of range 1.."
                f"{XES3G5M_QUESTION_COUNT}."
            )
        if question_id not in self.question_concept_map:
            raise DGEKTMappingError(
                f"XES3G5M question_id {question_id} is missing from the configured KC routes."
            )
        if not self.question_concept_map[question_id]:
            raise DGEKTMappingError(
                f"XES3G5M question_id {question_id} has no concept in the configured KC routes."
            )
        return question_id

    def _resolve_xes3g5m_concept_id(self, event: LearningEvent, question_id: int) -> int:
        mapped_concepts = self.question_concept_map[question_id]
        raw_concept_id = event.payload.get("xes3g5m_concept_id") or event.payload.get("dgekt_concept_id")
        if raw_concept_id is None:
            return mapped_concepts[0]
        concept_id = self._parse_xes3g5m_id(raw_concept_id, field_name="concept_id")
        if concept_id not in mapped_concepts:
            raise DGEKTMappingError(
                f"XES3G5M concept_id {concept_id} is inconsistent with KC routes mapping "
                f"for question_id {question_id}; expected one of {mapped_concepts}."
            )
        return concept_id

    def _parse_xes3g5m_id(self, raw_value: Any, *, field_name: str) -> int:
        if isinstance(raw_value, int):
            return raw_value
        value = str(raw_value)
        if value.startswith("xes3g5m:"):
            value = value.split(":", 1)[1]
        if not value.isdigit():
            raise DGEKTMappingError(
                f"Cannot map MathTutor {field_name} '{raw_value}' to XES3G5M. "
                f"Use an integer id or xes3g5m:<id>."
            )
        return int(value)

    def _one_hot_sequence(self, *, question_ids: list[int], answers: list[int]) -> Any:
        try:
            import torch
        except ImportError as exc:
            raise DGEKTCheckpointError("DGEKT input tensor construction requires torch.") from exc

        tensor = torch.zeros(
            1,
            XES3G5M_MAX_STEP,
            2 * XES3G5M_QUESTION_COUNT,
            device=self.runtime.device,
        )
        start = max(0, XES3G5M_MAX_STEP - len(question_ids))
        for offset, (question_id, answer) in enumerate(zip(question_ids, answers)):
            column = question_id - 1 if answer == 1 else XES3G5M_QUESTION_COUNT + question_id - 1
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

        target_xes3g5m_id = self._target_xes3g5m_question_id(
            inference_input=inference_input,
            target_question_id=target_question_id,
        )
        sequence_index = XES3G5M_MAX_STEP - 1
        with torch.no_grad():
            output = self.runtime.model(inference_input.tensor)
            if isinstance(output, tuple) and len(output) == 2:
                output = output[0]
            logit_ensemble = output[2]
            probability = torch.sigmoid(logit_ensemble)[0, sequence_index, target_xes3g5m_id - 1]
        return round(float(probability.detach().cpu().item()), 6)

    def _target_xes3g5m_question_id(
        self,
        *,
        inference_input: DGEKTInferenceInput,
        target_question_id: str | None,
    ) -> int:
        if target_question_id:
            try:
                target_id = self._parse_xes3g5m_id(
                    target_question_id,
                    field_name="target_question_id",
                )
                if target_id < 1 or target_id > XES3G5M_QUESTION_COUNT:
                    raise DGEKTUnsupportedTargetError(
                        f"XES3G5M target question_id {target_id} is out of range 1.."
                        f"{XES3G5M_QUESTION_COUNT}."
                    )
                if target_id not in self.question_concept_map:
                    raise DGEKTUnsupportedTargetError(
                        f"XES3G5M target question_id {target_id} is missing from the "
                        "configured KC routes."
                    )
                if not self.question_concept_map[target_id]:
                    raise DGEKTUnsupportedTargetError(
                        f"XES3G5M target question_id {target_id} has no concept in the "
                        "configured KC routes."
                    )
                return target_id
            except DGEKTUnsupportedTargetError:
                raise
            except DGEKTMappingError:
                pass
        return inference_input.question_ids[-1]

    def _prediction_weak_concepts(
        self,
        inference_input: DGEKTInferenceInput,
        prediction_probability: float,
    ) -> list[dict[str, Any]]:
        concept = inference_input.mathtutor_concepts[-1] if inference_input.mathtutor_concepts else {}
        concept_id = concept.get("concept_id") or f"xes3g5m_concept:{inference_input.concept_ids[-1]}"
        concept_name = concept.get("concept_name") or f"XES3G5M concept {inference_input.concept_ids[-1]}"
        mastery = prediction_probability
        if mastery >= 0.6:
            return []
        return [
            {
                "concept_id": concept_id,
                "concept_name": concept_name,
                "mastery": mastery,
                "prediction_probability": prediction_probability,
                "xes3g5m_concept_id": inference_input.concept_ids[-1],
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
                or f"xes3g5m_concept:{inference_input.concept_ids[-1]}",
                "concept_name": concept.get("concept_name")
                or f"XES3G5M concept {inference_input.concept_ids[-1]}",
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
        progress.recent_events = progress.recent_events[-XES3G5M_MAX_STEP:]
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
        inference_input = self.build_inference_input(progress)
        if inference_input is None:
            return AttributionEvidence(
                target_question_id=target_question_id,
                prediction_probability=None,
                evidence_status="partial",
                evidence_source="online_proxy",
                partial_evidence=True,
                partial_evidence_reason="No graded XES3G5M answer history is available.",
                raw_model_target={
                    "target_question_id": target_question_id,
                    "dataset": self.dataset,
                    "model_vocabulary": "DGEKT XES3G5M question id",
                    "mapping_status": "no_history",
                },
                mapped_teaching_content={
                    "question_id": target_question_id,
                    "mapping_status": "unavailable",
                    "missing_reason": "No graded XES3G5M answer history is available.",
                },
                scorer=self._scorer_metadata(
                    evidence_status="partial",
                    partial_evidence_reason="No graded XES3G5M answer history is available.",
                ),
                provenance=self._attribution_provenance(),
                top_paths=[
                    {
                        "path_id": "dgekt-partial-no-history",
                        "engine": "dgekt",
                        "scorer_name": DGEKT_ONLINE_SCORER_NAME,
                        "scorer_version": DGEKT_ONLINE_SCORER_VERSION,
                        "evidence_status": "partial",
                        "partial_evidence": True,
                        "partial_evidence_reason": "No graded XES3G5M answer history is available.",
                        "relation_source": DGEKT_RELATION_SOURCE,
                        "relation_strength": 0.0,
                        "path_strength": 0.0,
                        "weak_concept_hit": False,
                        "weak_concept_evidence": [],
                        "description": (
                            "No graded XES3G5M answer history is available, so DGEKT cannot "
                            "build online attribution paths for this turn."
                        ),
                    }
                ],
                key_history=[],
                weak_concepts=list(progress.weak_concepts),
            )

        prediction_probability = self._prediction_probability(inference_input, target_question_id)
        weak_concepts = self._prediction_weak_concepts(inference_input, prediction_probability)
        target_xes3g5m_id = self._target_xes3g5m_question_id(
            inference_input=inference_input,
            target_question_id=target_question_id,
        )
        target_concepts = self.question_concept_map.get(target_xes3g5m_id) or [
            inference_input.concept_ids[-1]
        ]
        target_concept_id = target_concepts[0]
        key_history = self._attribution_key_history(progress, inference_input)
        mapped_teaching_content = self._mapped_target_content(
            key_history=key_history,
            target_question_id=target_question_id,
            target_xes3g5m_id=target_xes3g5m_id,
            target_concept_id=target_concept_id,
        )
        top_paths = self._partial_attribution_paths(
            key_history=key_history,
            target_question_id=target_question_id,
            target_xes3g5m_id=target_xes3g5m_id,
            target_concept_id=target_concept_id,
            weak_concepts=weak_concepts,
        )
        fallback_evidence = AttributionEvidence(
            target_question_id=target_question_id,
            target_concept_id=mapped_teaching_content.get("concept_id"),
            target_xes3g5m_question_id=target_xes3g5m_id,
            target_xes3g5m_concept_id=target_concept_id,
            prediction_probability=prediction_probability,
            evidence_status="partial",
            evidence_source="online_proxy",
            partial_evidence=True,
            partial_evidence_reason=DGEKT_PARTIAL_ATTRIBUTION_REASON,
            raw_model_target={
                "target_question_id": target_question_id,
                "xes3g5m_question_id": target_xes3g5m_id,
                "xes3g5m_concept_id": target_concept_id,
                "dataset": self.dataset,
                "model_vocabulary": "DGEKT XES3G5M question/concept ids",
            },
            mapped_teaching_content=mapped_teaching_content,
            canonical_mapping={
                "xes3g5m_question_id": target_xes3g5m_id,
                "xes3g5m_concept_id": target_concept_id,
                "kc_routes_reference": {
                    "question_row": target_xes3g5m_id,
                    "concept_columns": target_concepts,
                    "relation_source": DGEKT_RELATION_SOURCE,
                },
                "source": mapped_teaching_content.get("mapping_status"),
            },
            scorer=self._scorer_metadata(
                evidence_status="partial",
                partial_evidence_reason=DGEKT_PARTIAL_ATTRIBUTION_REASON,
            ),
            provenance=self._attribution_provenance(),
            top_paths=top_paths,
            key_history=key_history,
            weak_concepts=weak_concepts,
        )
        if self.offline_evidence_adapter is None:
            return fallback_evidence

        offline_evidence = self.offline_evidence_adapter.explain_prediction(
            dataset=self.dataset,
            student_id=progress.student_id,
            target_question_id=target_question_id,
            target_xes3g5m_question_id=target_xes3g5m_id,
            target_xes3g5m_concept_id=target_concept_id,
            prediction_probability=prediction_probability,
            authoritative_weak_concepts=weak_concepts,
            checkpoint_provenance=self._checkpoint_provenance(),
            fallback_mapped_teaching_content=mapped_teaching_content,
            fallback_canonical_mapping=fallback_evidence.canonical_mapping,
        )
        if offline_evidence.evidence_status == "complete":
            return offline_evidence
        return self._offline_gap_with_partial_fallback(
            offline_evidence=offline_evidence,
            fallback_evidence=fallback_evidence,
        )

    def _scorer_metadata(
        self,
        *,
        evidence_status: str,
        partial_evidence_reason: str,
    ) -> dict[str, Any]:
        return {
            "name": DGEKT_ONLINE_SCORER_NAME,
            "version": DGEKT_ONLINE_SCORER_VERSION,
            "engine": "dgekt",
            "dataset": self.dataset,
            "relation_source": DGEKT_RELATION_SOURCE,
            "evidence_status": evidence_status,
            "partial_evidence": evidence_status == "partial",
            "partial_evidence_reason": partial_evidence_reason,
            "vocabulary": [
                "DGEKT",
                "XES3G5M question_id",
                "XES3G5M concept_id",
                "KC routes",
                "recent history",
                "top attribution paths",
            ],
        }

    def _offline_gap_with_partial_fallback(
        self,
        *,
        offline_evidence: AttributionEvidence,
        fallback_evidence: AttributionEvidence,
    ) -> AttributionEvidence:
        status = offline_evidence.evidence_status or "unavailable"
        offline_reason = (
            offline_evidence.partial_evidence_reason
            or "Offline DGEKT evidence is not available for this prediction."
        )
        fallback_reason = (
            f"{offline_reason} Online partial proxy fallback remains available, but it is not "
            "complete offline attribution evidence."
        )
        fallback_paths = [
            path
            | {
                "offline_evidence_status": status,
                "offline_evidence_gap_categories": [
                    gap.get("category") or gap.get("gap_type")
                    for gap in offline_evidence.evidence_gaps
                ],
            }
            for path in fallback_evidence.top_paths
        ]
        scorer = dict(offline_evidence.scorer)
        scorer.update(
            {
                "partial_evidence": True,
                "partial_evidence_reason": fallback_reason,
                "fallback_scorer": fallback_evidence.scorer,
                "fallback_evidence_source": "online_proxy",
            }
        )
        provenance = dict(fallback_evidence.provenance)
        provenance["offline_evidence"] = offline_evidence.provenance
        return fallback_evidence.model_copy(
            update={
                "evidence_status": status,
                "evidence_source": offline_evidence.evidence_source or "offline",
                "partial_evidence": True,
                "partial_evidence_reason": fallback_reason,
                "scorer": scorer,
                "provenance": provenance,
                "top_paths": fallback_paths,
                "path_ablation": offline_evidence.path_ablation,
                "evidence_gaps": offline_evidence.evidence_gaps,
            }
        )

    def _attribution_provenance(self) -> dict[str, Any]:
        return {
            "checkpoint_path": str(self.paths.checkpoint_path),
            "checkpoint_id": self.metadata.get("checkpoint_id"),
            "dataset_dir": str(self.paths.dataset_dir),
            "kc_routes_path": str(self.paths.kc_routes_path),
            "model_epoch": self.metadata.get("epoch"),
            "model_auc": self.metadata.get("auc"),
            "model_acc": self.metadata.get("acc"),
            "source": "online_dgekt_adapter",
            "offline_path_scorer_available": self.offline_evidence_adapter is not None,
        }

    def _checkpoint_provenance(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "checkpoint_path": str(self.paths.checkpoint_path),
            "checkpoint_id": self.metadata.get("checkpoint_id"),
            "epoch": self.metadata.get("epoch"),
            "auc": self.metadata.get("auc"),
            "acc": self.metadata.get("acc"),
            "device": self.metadata.get("device"),
        }

    def _mapped_target_content(
        self,
        *,
        key_history: list[dict[str, Any]],
        target_question_id: str,
        target_xes3g5m_id: int,
        target_concept_id: int,
    ) -> dict[str, Any]:
        for history in reversed(key_history):
            if (
                history.get("question_id") == target_question_id
                or history.get("xes3g5m_question_id") == target_xes3g5m_id
            ):
                return {
                    "question_id": history.get("question_id") or target_question_id,
                    "concept_id": history.get("concept_id")
                    or f"xes3g5m_concept:{target_concept_id}",
                    "concept_name": history.get("concept_name")
                    or f"XES3G5M concept {target_concept_id}",
                    "xes3g5m_question_id": target_xes3g5m_id,
                    "xes3g5m_concept_id": target_concept_id,
                    "mapping_status": "recent_history_canonical_payload",
                    "relation_source": DGEKT_RELATION_SOURCE,
                }

        return {
            "question_id": target_question_id,
            "concept_id": f"xes3g5m_concept:{target_concept_id}",
            "concept_name": f"XES3G5M concept {target_concept_id}",
            "xes3g5m_question_id": target_xes3g5m_id,
            "xes3g5m_concept_id": target_concept_id,
            "mapping_status": "kc_routes_only",
            "relation_source": DGEKT_RELATION_SOURCE,
        }

    def _attribution_key_history(
        self,
        progress: KTLearningProgress,
        inference_input: DGEKTInferenceInput,
    ) -> list[dict[str, Any]]:
        events = self._graded_answer_events(progress)
        key_history: list[dict[str, Any]] = []
        start_position = max(0, XES3G5M_MAX_STEP - len(inference_input.question_ids))
        for index, (event, question_id, answer, concept_id, concept) in enumerate(
            zip(
                events,
                inference_input.question_ids,
                inference_input.answers,
                inference_input.concept_ids,
                inference_input.mathtutor_concepts,
            )
        ):
            key_history.append(
                {
                    "event_type": event.type,
                    "question_id": event.payload.get("question_id"),
                    "xes3g5m_question_id": question_id,
                    "is_correct": answer == 1,
                    "answer": answer,
                    "history_position": start_position + index,
                    "sequence_offset": index,
                    "concept_id": concept.get("concept_id"),
                    "concept_name": concept.get("concept_name"),
                    "xes3g5m_concept_id": concept_id,
                    "influence_source": "recent_dgekt_input",
                    "readable_summary": (
                        f"XES3G5M Q{question_id} | "
                        f"{'correct' if answer == 1 else 'incorrect'} | "
                        f"concept {concept_id}"
                    ),
                }
            )
        return key_history[-5:]

    def _partial_attribution_paths(
        self,
        *,
        key_history: list[dict[str, Any]],
        target_question_id: str,
        target_xes3g5m_id: int,
        target_concept_id: int,
        weak_concepts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        paths: list[dict[str, Any]] = []
        for rank, history in enumerate(reversed(key_history), start=1):
            history_concept_id = history.get("xes3g5m_concept_id")
            concept_relation_strength = 1.0 if history_concept_id == target_concept_id else 0.0
            question_relation_strength = (
                1.0 if history.get("xes3g5m_question_id") == target_xes3g5m_id else 0.0
            )
            recency_strength = round(1.0 / rank, 6)
            relation_strength = max(concept_relation_strength, question_relation_strength)
            path_weight = round(
                (0.55 * recency_strength)
                + (0.30 * concept_relation_strength)
                + (0.15 * question_relation_strength),
                6,
            )
            weak_concept_evidence = self._weak_concept_hit_evidence(
                weak_concepts=weak_concepts,
                target_concept_id=target_concept_id,
                history_concept_id=history_concept_id,
            )
            paths.append(
                {
                    "path_id": (
                        f"dgekt-partial-{history.get('xes3g5m_question_id')}-"
                        f"{target_xes3g5m_id}-{rank}"
                    ),
                    "engine": "dgekt",
                    "scorer_name": DGEKT_ONLINE_SCORER_NAME,
                    "scorer_version": DGEKT_ONLINE_SCORER_VERSION,
                    "path_type": "recent_history_to_target_concept",
                    "evidence_status": "partial",
                    "partial_evidence": True,
                    "partial_evidence_reason": DGEKT_PARTIAL_ATTRIBUTION_REASON,
                    "rank": rank,
                    "history_question_id": history.get("question_id"),
                    "history_xes3g5m_question_id": history.get("xes3g5m_question_id"),
                    "history_answer": history.get("answer"),
                    "history_is_correct": history.get("is_correct"),
                    "history_readable_summary": history.get("readable_summary"),
                    "history_position": history.get("history_position"),
                    "history_concept_id": history.get("concept_id"),
                    "history_xes3g5m_concept_id": history_concept_id,
                    "target_question_id": target_question_id,
                    "target_xes3g5m_question_id": target_xes3g5m_id,
                    "target_concept_id": f"xes3g5m_concept:{target_concept_id}",
                    "target_xes3g5m_concept_id": target_concept_id,
                    "time_gap": max(
                        0,
                        XES3G5M_MAX_STEP - 1 - int(history.get("history_position", 0)),
                    ),
                    "concept_relation_strength": concept_relation_strength,
                    "question_relation_strength": question_relation_strength,
                    "relation_strength": relation_strength,
                    "relation_source": DGEKT_RELATION_SOURCE,
                    "recency_strength": recency_strength,
                    "path_weight": path_weight,
                    "path_strength": path_weight,
                    "graph_source": DGEKT_RELATION_SOURCE,
                    "weak_concept_hit": bool(weak_concept_evidence),
                    "weak_concept_evidence": weak_concept_evidence,
                    "limitations": (
                        "Online MathTutor currently exposes recent sequence and KC routes concept "
                        "links, not the original offline DGEKT path scorer; treat this as partial "
                        "attribution evidence."
                    ),
                }
            )
        return sorted(paths, key=lambda path: path["path_weight"], reverse=True)[:5]

    def _weak_concept_hit_evidence(
        self,
        *,
        weak_concepts: list[dict[str, Any]],
        target_concept_id: int,
        history_concept_id: Any,
    ) -> list[dict[str, Any]]:
        hit_concept_ids = {
            str(target_concept_id),
            f"xes3g5m_concept:{target_concept_id}",
        }
        if history_concept_id is not None:
            hit_concept_ids.add(str(history_concept_id))
            hit_concept_ids.add(f"xes3g5m_concept:{history_concept_id}")

        evidence: list[dict[str, Any]] = []
        for weak in weak_concepts:
            assist_concept = weak.get("xes3g5m_concept_id")
            concept_id = weak.get("concept_id")
            if (
                (assist_concept is not None and str(assist_concept) in hit_concept_ids)
                or (concept_id is not None and str(concept_id) in hit_concept_ids)
            ):
                evidence.append(
                    {
                        "concept_id": concept_id,
                        "concept_name": weak.get("concept_name"),
                        "xes3g5m_concept_id": assist_concept,
                        "mastery": weak.get("mastery"),
                        "prediction_probability": weak.get("prediction_probability"),
                        "hit_source": "dgekt_weak_concept_proxy",
                    }
                )
        return evidence
