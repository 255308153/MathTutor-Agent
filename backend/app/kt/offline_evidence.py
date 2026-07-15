from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..mapping.xes3g5m_mapping import (
    CanonicalMappingRepository,
    DEFAULT_MAPPING_PATH,
)
from ..schemas.learning import AttributionEvidence


OFFLINE_EVIDENCE_SCHEMA_VERSION = "dgekt-offline-evidence/v1"
OFFLINE_SCORER_DEFAULT_NAME = "dgekt_offline_path_scorer"
OFFLINE_SCORER_DEFAULT_VERSION = "unknown"

EvidenceGapCategory = Literal[
    "missing_artifact",
    "missing_column",
    "malformed_row",
    "invalid_numeric_value",
    "duplicate_sample",
    "target_not_found",
    "canonical_mapping_mismatch",
    "checkpoint_provenance_mismatch",
]

REQUIRED_FILES = {
    "attribution_paths.csv": {
        "sample_id",
        "dataset",
        "student_id",
        "time_step",
        "target_question_id",
        "target_concept_id",
        "canonical_question_id",
        "canonical_concept_id",
        "checkpoint_id",
        "path_rank",
        "path_id",
        "path_type",
        "path_nodes",
        "history_question_id",
        "history_answer",
        "history_position",
        "history_concept_id",
        "relation_strength",
        "graph_relation_strength",
        "path_score",
        "risk_score",
        "mastery_score",
    },
    "key_history.csv": {
        "sample_id",
        "dataset",
        "student_id",
        "time_step",
        "target_question_id",
        "target_concept_id",
        "canonical_target_question_id",
        "canonical_target_concept_id",
        "checkpoint_id",
        "history_rank",
        "history_question_id",
        "history_canonical_question_id",
        "history_concept_id",
        "history_canonical_concept_id",
        "history_answer",
        "history_is_correct",
        "history_position",
        "influence_score",
    },
    "path_ablation.csv": {
        "sample_id",
        "dataset",
        "student_id",
        "time_step",
        "target_question_id",
        "target_concept_id",
        "canonical_question_id",
        "canonical_concept_id",
        "checkpoint_id",
        "strategy",
        "k",
        "path_ids",
        "original_prediction",
        "ablated_prediction",
        "impact",
        "comprehensiveness",
        "warnings",
    },
    "weak_concepts.csv": {
        "sample_id",
        "dataset",
        "student_id",
        "time_step",
        "target_question_id",
        "target_concept_id",
        "canonical_question_id",
        "canonical_concept_id",
        "checkpoint_id",
        "weak_concept_id",
        "weak_canonical_concept_id",
        "concept_name",
        "mastery_score",
        "risk_score",
        "hit",
        "path_ids",
        "evidence_source",
    },
}


class OfflineEvidenceGap(BaseModel):
    category: EvidenceGapCategory
    reason_code: str = Field(min_length=1)
    severity: Literal["error", "warning", "info"] = "warning"
    message: str = Field(min_length=1)
    actionable_hint: str = Field(min_length=1)
    source_ref: str | None = None
    sample_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    def as_trace_gap(self) -> dict[str, Any]:
        return {
            "gap_type": self.category,
            "category": self.category,
            "reason_code": self.reason_code,
            "reason": self.message,
            "message": self.message,
            "impact": self.actionable_hint,
            "actionable_hint": self.actionable_hint,
            "severity": self.severity,
            "recoverable": True,
            "stage": "diagnose",
            "code": self.reason_code,
            "source_ref": self.source_ref,
            "sample_id": self.sample_id,
            "details": self.details,
        }


@dataclass(frozen=True)
class OfflineEvidenceCase:
    sample_id: str
    dataset: str
    student_id: str | None
    time_step: int | None
    target_question_id: int
    target_concept_id: int | None
    canonical_question_id: str | None
    canonical_concept_id: str | None
    checkpoint_id: str | None
    prediction_probability: float | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class OfflineEvidenceMatch:
    case: OfflineEvidenceCase
    matching_method: str


class DGEKTOfflineEvidenceAdapter:
    """Read original DGEKT explainability outputs into MathTutor evidence.

    The adapter is intentionally local-file only. Full DGEKT explainability outputs stay
    opt-in and outside Git; committed tests use a tiny fixture with the same file names.
    """

    def __init__(
        self,
        artifact_dir: str | Path,
        *,
        canonical_mapping_path: str | Path | None = DEFAULT_MAPPING_PATH,
    ) -> None:
        self.artifact_dir = Path(artifact_dir).expanduser()
        self.canonical_mapping_path = canonical_mapping_path
        self.load_gaps: list[OfflineEvidenceGap] = []
        self.diagnosis_payload: dict[str, Any] = {}
        self.scorer: dict[str, Any] = {}
        self.artifact_provenance: dict[str, Any] = {}
        self.checkpoint_provenance: dict[str, Any] = {}
        self.cases: dict[str, OfflineEvidenceCase] = {}
        self.rows: dict[str, list[dict[str, str]]] = {}
        self.mapping_repository = self._load_mapping_repository(canonical_mapping_path)
        self._load()

    def explain_prediction(
        self,
        *,
        dataset: str,
        student_id: str,
        target_question_id: str,
        target_xes3g5m_question_id: int,
        target_xes3g5m_concept_id: int | None,
        prediction_probability: float | None,
        authoritative_weak_concepts: list[dict[str, Any]],
        checkpoint_provenance: dict[str, Any],
        fallback_mapped_teaching_content: dict[str, Any] | None = None,
        fallback_canonical_mapping: dict[str, Any] | None = None,
    ) -> AttributionEvidence:
        if self.load_gaps:
            return self._gap_evidence(
                status=_status_for_load_gaps(self.load_gaps),
                target_question_id=target_question_id,
                target_xes3g5m_question_id=target_xes3g5m_question_id,
                target_xes3g5m_concept_id=target_xes3g5m_concept_id,
                prediction_probability=prediction_probability,
                weak_concepts=authoritative_weak_concepts,
                gaps=self.load_gaps,
                fallback_mapped_teaching_content=fallback_mapped_teaching_content,
                fallback_canonical_mapping=fallback_canonical_mapping,
            )

        match = self._find_case(
            dataset=dataset,
            student_id=student_id,
            target_xes3g5m_question_id=target_xes3g5m_question_id,
            target_xes3g5m_concept_id=target_xes3g5m_concept_id,
        )
        if match is None:
            gap = OfflineEvidenceGap(
                category="target_not_found",
                reason_code="offline_evidence_target_not_found",
                severity="warning",
                message=(
                    "Offline DGEKT evidence artifact does not contain a matching target "
                    f"for student={student_id}, question={target_xes3g5m_question_id}, "
                    f"concept={target_xes3g5m_concept_id}."
                ),
                actionable_hint=(
                    "确认 offline explainability 输出覆盖当前 sample/student/time step，"
                    "或仅把本轮展示为 partial proxy evidence。"
                ),
                details={
                    "dataset": dataset,
                    "student_id": student_id,
                    "target_xes3g5m_question_id": target_xes3g5m_question_id,
                    "target_xes3g5m_concept_id": target_xes3g5m_concept_id,
                },
            )
            return self._gap_evidence(
                status="unavailable",
                target_question_id=target_question_id,
                target_xes3g5m_question_id=target_xes3g5m_question_id,
                target_xes3g5m_concept_id=target_xes3g5m_concept_id,
                prediction_probability=prediction_probability,
                weak_concepts=authoritative_weak_concepts,
                gaps=[gap],
                fallback_mapped_teaching_content=fallback_mapped_teaching_content,
                fallback_canonical_mapping=fallback_canonical_mapping,
            )

        validation_gaps = [
            *self._checkpoint_mismatch_gaps(match.case, checkpoint_provenance),
            *self._canonical_mapping_gaps(
                match.case,
                requested_target_question_id=target_question_id,
                requested_target_xes3g5m_question_id=target_xes3g5m_question_id,
                requested_target_xes3g5m_concept_id=target_xes3g5m_concept_id,
            ),
        ]
        if validation_gaps:
            return self._gap_evidence(
                status="invalid",
                target_question_id=target_question_id,
                target_xes3g5m_question_id=target_xes3g5m_question_id,
                target_xes3g5m_concept_id=target_xes3g5m_concept_id,
                prediction_probability=prediction_probability,
                weak_concepts=authoritative_weak_concepts,
                gaps=validation_gaps,
                sample_id=match.case.sample_id,
                fallback_mapped_teaching_content=fallback_mapped_teaching_content,
                fallback_canonical_mapping=fallback_canonical_mapping,
            )

        normalized_gaps: list[OfflineEvidenceGap] = []
        top_paths = self._top_paths(match.case.sample_id, normalized_gaps)
        key_history = self._key_history(match.case.sample_id, normalized_gaps)
        weak_concepts = self._weak_concepts(match.case.sample_id, normalized_gaps)
        path_ablation = self._path_ablation(match.case.sample_id, normalized_gaps)
        if normalized_gaps:
            return self._gap_evidence(
                status="invalid",
                target_question_id=target_question_id,
                target_xes3g5m_question_id=target_xes3g5m_question_id,
                target_xes3g5m_concept_id=target_xes3g5m_concept_id,
                prediction_probability=prediction_probability,
                weak_concepts=authoritative_weak_concepts,
                gaps=normalized_gaps,
                sample_id=match.case.sample_id,
                fallback_mapped_teaching_content=fallback_mapped_teaching_content,
                fallback_canonical_mapping=fallback_canonical_mapping,
            )

        mapped_content = self._mapped_teaching_content(
            match.case,
            fallback=fallback_mapped_teaching_content,
        )
        canonical_mapping = self._canonical_mapping(
            match.case,
            fallback=fallback_canonical_mapping,
        )
        probability = prediction_probability
        return AttributionEvidence(
            target_question_id=target_question_id,
            target_concept_id=mapped_content.get("concept_id") or match.case.canonical_concept_id,
            target_xes3g5m_question_id=match.case.target_question_id,
            target_xes3g5m_concept_id=match.case.target_concept_id,
            prediction_probability=probability,
            evidence_status="complete",
            evidence_source="offline",
            partial_evidence=False,
            partial_evidence_reason=None,
            raw_model_target={
                "sample_id": match.case.sample_id,
                "dataset": match.case.dataset,
                "student_id": match.case.student_id,
                "time_step": match.case.time_step,
                "target_question_id": match.case.target_question_id,
                "target_concept_id": match.case.target_concept_id,
                "canonical_question_id": match.case.canonical_question_id,
                "canonical_concept_id": match.case.canonical_concept_id,
                "checkpoint_id": match.case.checkpoint_id,
                "matching_method": match.matching_method,
                "model_vocabulary": "DGEKT XES3G5M question/concept ids",
            },
            mapped_teaching_content=mapped_content,
            canonical_mapping=canonical_mapping,
            scorer=self._scorer_metadata(
                evidence_status="complete",
                matching_method=match.matching_method,
                sample_id=match.case.sample_id,
                checkpoint_provenance=checkpoint_provenance,
            ),
            provenance=self._provenance(match.case, checkpoint_provenance),
            top_paths=top_paths,
            key_history=key_history,
            weak_concepts=weak_concepts,
            path_ablation=path_ablation,
            evidence_gaps=[],
        )

    def _load(self) -> None:
        if not self.artifact_dir.is_dir():
            self.load_gaps.append(
                OfflineEvidenceGap(
                    category="missing_artifact",
                    reason_code="offline_evidence_dir_missing",
                    severity="error",
                    message=f"DGEKT offline evidence directory not found: {self.artifact_dir}.",
                    actionable_hint=(
                        "设置 MATHTUTOR_DGEKT_OFFLINE_EVIDENCE_DIR 指向包含 attribution_paths.csv、"
                        "key_history.csv、path_ablation.csv、weak_concepts.csv 和 diagnosis_cases.json 的目录。"
                    ),
                    source_ref=str(self.artifact_dir),
                )
            )
            return

        self.diagnosis_payload = self._load_diagnosis_cases()
        self.scorer = dict(self.diagnosis_payload.get("scorer") or {})
        self.artifact_provenance = dict(self.diagnosis_payload.get("provenance") or {})
        self.checkpoint_provenance = dict(
            self.diagnosis_payload.get("checkpoint_provenance") or {}
        )
        self.cases = self._load_cases(self.diagnosis_payload)

        for filename, required_columns in REQUIRED_FILES.items():
            self.rows[filename] = self._load_csv(filename, required_columns)

    def _load_mapping_repository(
        self,
        path: str | Path | None,
    ) -> CanonicalMappingRepository | None:
        if path is None or str(path) == "":
            return None
        resolved = _resolve_project_path(path)
        if not resolved.is_file():
            return None
        return CanonicalMappingRepository.from_path(resolved)

    def _load_diagnosis_cases(self) -> dict[str, Any]:
        path = self.artifact_dir / "diagnosis_cases.json"
        if not path.is_file():
            self.load_gaps.append(
                OfflineEvidenceGap(
                    category="missing_artifact",
                    reason_code="diagnosis_cases_missing",
                    severity="error",
                    message="DGEKT offline evidence artifact is missing diagnosis_cases.json.",
                    actionable_hint="重新导出原 DGEKT explainability outputs，或使用 fixture 目录运行 smoke。",
                    source_ref=str(path),
                )
            )
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            self.load_gaps.append(
                OfflineEvidenceGap(
                    category="malformed_row",
                    reason_code="diagnosis_cases_invalid_json",
                    severity="error",
                    message=f"diagnosis_cases.json is not valid JSON: {exc}.",
                    actionable_hint="修复 diagnosis_cases.json 后重新加载 offline evidence。",
                    source_ref=str(path),
                )
            )
            return {}
        if not isinstance(raw, dict):
            self.load_gaps.append(
                OfflineEvidenceGap(
                    category="malformed_row",
                    reason_code="diagnosis_cases_not_object",
                    severity="error",
                    message="diagnosis_cases.json must be a JSON object.",
                    actionable_hint="使用包含 scorer/provenance/cases 的 diagnosis_cases.json artifact。",
                    source_ref=str(path),
                )
            )
            return {}
        return raw

    def _load_cases(self, payload: dict[str, Any]) -> dict[str, OfflineEvidenceCase]:
        cases: dict[str, OfflineEvidenceCase] = {}
        raw_cases = payload.get("cases") or []
        if not isinstance(raw_cases, list):
            self.load_gaps.append(
                OfflineEvidenceGap(
                    category="malformed_row",
                    reason_code="diagnosis_cases_cases_not_list",
                    severity="error",
                    message="diagnosis_cases.json field 'cases' must be a list.",
                    actionable_hint="重新导出 diagnosis cases，确保 cases 是数组。",
                    source_ref=str(self.artifact_dir / "diagnosis_cases.json"),
                )
            )
            return cases

        for index, item in enumerate(raw_cases, start=1):
            if not isinstance(item, dict):
                self.load_gaps.append(
                    OfflineEvidenceGap(
                        category="malformed_row",
                        reason_code="diagnosis_case_not_object",
                        severity="error",
                        message=f"diagnosis_cases.json case #{index} is not an object.",
                        actionable_hint="删除或修复 malformed diagnosis case。",
                        source_ref=f"{self.artifact_dir / 'diagnosis_cases.json'}:case:{index}",
                    )
                )
                continue
            sample_id = str(item.get("sample_id") or "")
            if not sample_id:
                self.load_gaps.append(
                    OfflineEvidenceGap(
                        category="malformed_row",
                        reason_code="diagnosis_case_missing_sample_id",
                        severity="error",
                        message=f"diagnosis case #{index} is missing sample_id.",
                        actionable_hint="为每个 diagnosis case 写入稳定 sample_id。",
                        source_ref=f"{self.artifact_dir / 'diagnosis_cases.json'}:case:{index}",
                    )
                )
                continue
            if sample_id in cases:
                self.load_gaps.append(
                    OfflineEvidenceGap(
                        category="duplicate_sample",
                        reason_code="duplicate_diagnosis_sample_id",
                        severity="error",
                        message=f"Duplicate DGEKT offline evidence sample_id: {sample_id}.",
                        actionable_hint="确保 diagnosis_cases.json 中 sample_id 唯一。",
                        source_ref=f"{self.artifact_dir / 'diagnosis_cases.json'}:case:{index}",
                        sample_id=sample_id,
                    )
                )
                continue
            target_question_id = _optional_int(item.get("target_question_id"))
            if target_question_id is None:
                self.load_gaps.append(
                    OfflineEvidenceGap(
                        category="malformed_row",
                        reason_code="diagnosis_case_missing_target_question",
                        severity="error",
                        message=f"Diagnosis case {sample_id} is missing target_question_id.",
                        actionable_hint="写入 XES3G5M target_question_id 后重新导出。",
                        source_ref=f"{self.artifact_dir / 'diagnosis_cases.json'}:case:{index}",
                        sample_id=sample_id,
                    )
                )
                continue
            cases[sample_id] = OfflineEvidenceCase(
                sample_id=sample_id,
                dataset=str(item.get("dataset") or payload.get("dataset") or "xes3g5m"),
                student_id=str(item["student_id"]) if item.get("student_id") is not None else None,
                time_step=_optional_int(item.get("time_step")),
                target_question_id=target_question_id,
                target_concept_id=_optional_int(item.get("target_concept_id")),
                canonical_question_id=_optional_str(item.get("canonical_question_id")),
                canonical_concept_id=_optional_str(item.get("canonical_concept_id")),
                checkpoint_id=_optional_str(item.get("checkpoint_id"))
                or _optional_str(self.checkpoint_provenance.get("checkpoint_id")),
                prediction_probability=_optional_float(item.get("prediction_probability")),
                raw=item,
            )
        return cases

    def _load_csv(self, filename: str, required_columns: set[str]) -> list[dict[str, str]]:
        path = self.artifact_dir / filename
        if not path.is_file():
            self.load_gaps.append(
                OfflineEvidenceGap(
                    category="missing_artifact",
                    reason_code=f"{Path(filename).stem}_missing",
                    severity="error",
                    message=f"DGEKT offline evidence artifact is missing {filename}.",
                    actionable_hint="重新导出完整 offline explainability outputs，或改用 fixture smoke。",
                    source_ref=str(path),
                )
            )
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            columns = set(reader.fieldnames or [])
            missing = sorted(required_columns - columns)
            if missing:
                self.load_gaps.append(
                    OfflineEvidenceGap(
                        category="missing_column",
                        reason_code=f"{Path(filename).stem}_missing_columns",
                        severity="error",
                        message=f"{filename} is missing required column(s): {', '.join(missing)}.",
                        actionable_hint="按 V1.6 offline evidence contract 补齐 CSV 列后重新导出。",
                        source_ref=str(path),
                        details={"missing_columns": missing},
                    )
                )
                return []
            rows: list[dict[str, str]] = []
            for row_number, row in enumerate(reader, start=2):
                if any(key is None for key in row):
                    self.load_gaps.append(
                        OfflineEvidenceGap(
                            category="malformed_row",
                            reason_code=f"{Path(filename).stem}_extra_columns",
                            severity="error",
                            message=f"{filename} row {row_number} has extra unnamed column values.",
                            actionable_hint="检查 CSV 引号和分隔符，确保列数量稳定。",
                            source_ref=f"{path}:row:{row_number}",
                        )
                    )
                    continue
                rows.append({key: (value or "").strip() for key, value in row.items()})
            return rows

    def _find_case(
        self,
        *,
        dataset: str,
        student_id: str,
        target_xes3g5m_question_id: int,
        target_xes3g5m_concept_id: int | None,
    ) -> OfflineEvidenceMatch | None:
        candidates = [
            case
            for case in self.cases.values()
            if case.dataset == dataset
            and case.target_question_id == target_xes3g5m_question_id
            and (
                target_xes3g5m_concept_id is None
                or case.target_concept_id is None
                or case.target_concept_id == target_xes3g5m_concept_id
            )
        ]
        exact = [case for case in candidates if case.student_id == student_id]
        if exact:
            return OfflineEvidenceMatch(
                case=sorted(exact, key=lambda item: (item.time_step or 0, item.sample_id))[-1],
                matching_method="student_target_exact",
            )
        target_only_candidates = [case for case in candidates if case.student_id is None]
        if len(target_only_candidates) == 1:
            return OfflineEvidenceMatch(
                case=target_only_candidates[0],
                matching_method="target_only_no_student",
            )
        if target_only_candidates:
            return OfflineEvidenceMatch(
                case=sorted(
                    target_only_candidates,
                    key=lambda item: (item.time_step or 0, item.sample_id),
                )[-1],
                matching_method="target_best_effort_no_student",
            )
        return None

    def _checkpoint_mismatch_gaps(
        self,
        case: OfflineEvidenceCase,
        expected: dict[str, Any],
    ) -> list[OfflineEvidenceGap]:
        mismatches: dict[str, dict[str, Any]] = {}
        evidence_checkpoint = {
            **self.checkpoint_provenance,
            "checkpoint_id": case.checkpoint_id or self.checkpoint_provenance.get("checkpoint_id"),
        }
        for key in ("dataset", "checkpoint_id", "epoch", "auc", "acc"):
            expected_value = expected.get(key)
            evidence_value = evidence_checkpoint.get(key)
            if expected_value in (None, "") or evidence_value in (None, ""):
                continue
            if str(expected_value) == str(evidence_value):
                continue
            if key in {"auc", "acc"}:
                expected_number = _optional_float(expected_value)
                evidence_number = _optional_float(evidence_value)
                if (
                    expected_number is not None
                    and evidence_number is not None
                    and abs(expected_number - evidence_number) <= 1e-9
                ):
                    continue
            mismatches[key] = {
                "runtime": expected_value,
                "offline_evidence": evidence_value,
            }
        if not mismatches:
            return []
        return [
            OfflineEvidenceGap(
                category="checkpoint_provenance_mismatch",
                reason_code="checkpoint_provenance_mismatch",
                severity="error",
                message=(
                    "Offline attribution evidence was generated from checkpoint provenance "
                    "that does not match the active DGEKT runtime."
                ),
                actionable_hint=(
                    "使用同一 checkpoint 重新生成 offline explainability 输出，或修正 "
                    "MATHTUTOR_DGEKT_CHECKPOINT_ID / checkpoint metadata。"
                ),
                sample_id=case.sample_id,
                details={"mismatches": mismatches},
            )
        ]

    def _canonical_mapping_gaps(
        self,
        case: OfflineEvidenceCase,
        *,
        requested_target_question_id: str,
        requested_target_xes3g5m_question_id: int,
        requested_target_xes3g5m_concept_id: int | None,
    ) -> list[OfflineEvidenceGap]:
        mismatches: dict[str, dict[str, Any]] = {}
        if case.target_question_id != requested_target_xes3g5m_question_id:
            mismatches["target_question_id"] = {
                "request": requested_target_xes3g5m_question_id,
                "offline_evidence": case.target_question_id,
            }
        if (
            requested_target_xes3g5m_concept_id is not None
            and case.target_concept_id is not None
            and case.target_concept_id != requested_target_xes3g5m_concept_id
        ):
            mismatches["target_concept_id"] = {
                "request": requested_target_xes3g5m_concept_id,
                "offline_evidence": case.target_concept_id,
            }
        if requested_target_question_id.startswith("q_") and case.canonical_question_id:
            if requested_target_question_id != case.canonical_question_id:
                mismatches["canonical_question_id"] = {
                    "request": requested_target_question_id,
                    "offline_evidence": case.canonical_question_id,
                }
        mapping = (
            self.mapping_repository.get_by_xes3g5m_question_id(case.target_question_id)
            if self.mapping_repository is not None
            else None
        )
        if mapping is not None:
            if case.canonical_question_id and mapping.question_id != case.canonical_question_id:
                mismatches["mapping_repository_question_id"] = {
                    "canonical_mapping": mapping.question_id,
                    "offline_evidence": case.canonical_question_id,
                }
            if case.canonical_concept_id and mapping.concept_id != case.canonical_concept_id:
                mismatches["mapping_repository_concept_id"] = {
                    "canonical_mapping": mapping.concept_id,
                    "offline_evidence": case.canonical_concept_id,
                }
            if (
                case.target_concept_id is not None
                and mapping.xes3g5m_concept_id is not None
                and mapping.xes3g5m_concept_id != case.target_concept_id
            ):
                mismatches["mapping_repository_xes3g5m_concept_id"] = {
                    "canonical_mapping": mapping.xes3g5m_concept_id,
                    "offline_evidence": case.target_concept_id,
                }
        if not mismatches:
            return []
        return [
            OfflineEvidenceGap(
                category="canonical_mapping_mismatch",
                reason_code="canonical_mapping_mismatch",
                severity="error",
                message=(
                    "Offline attribution evidence target does not match MathTutor canonical "
                    "question/concept mapping."
                ),
                actionable_hint=(
                    "确认 offline scorer 使用的 XES3G5M id 与当前 canonical mapping "
                    "artifact 同源，避免解释指向错误教学内容。"
                ),
                sample_id=case.sample_id,
                details={"mismatches": mismatches},
            )
        ]

    def _top_paths(
        self,
        sample_id: str,
        gaps: list[OfflineEvidenceGap],
    ) -> list[dict[str, Any]]:
        rows = self._rows_for_sample("attribution_paths.csv", sample_id)
        paths = []
        for row in rows:
            parsed = self._parse_row(
                row,
                filename="attribution_paths.csv",
                sample_id=sample_id,
                gaps=gaps,
                integer_fields=["path_rank", "target_question_id", "target_concept_id", "history_question_id", "history_position", "history_concept_id"],
                float_fields=[
                    "relation_strength",
                    "graph_relation_strength",
                    "path_score",
                    "risk_score",
                    "mastery_score",
                ],
            )
            if parsed is None:
                continue
            paths.append(
                {
                    "path_id": row["path_id"],
                    "rank": parsed["path_rank"],
                    "path_type": row["path_type"],
                    "path_nodes": _parse_json_or_pipe(row.get("path_nodes")),
                    "history_xes3g5m_question_id": parsed["history_question_id"],
                    "history_question_id": _optional_str(row.get("history_canonical_question_id")),
                    "history_answer": row.get("history_answer"),
                    "history_position": parsed["history_position"],
                    "history_xes3g5m_concept_id": parsed["history_concept_id"],
                    "history_concept_id": _optional_str(row.get("history_canonical_concept_id")),
                    "target_xes3g5m_question_id": parsed["target_question_id"],
                    "target_question_id": _optional_str(row.get("canonical_question_id")),
                    "target_xes3g5m_concept_id": parsed["target_concept_id"],
                    "target_concept_id": _optional_str(row.get("canonical_concept_id")),
                    "relation_strength": parsed["relation_strength"],
                    "graph_relation_strength": parsed["graph_relation_strength"],
                    "path_score": parsed["path_score"],
                    "path_strength": parsed["path_score"],
                    "risk_score": parsed["risk_score"],
                    "mastery_score": parsed["mastery_score"],
                    "evidence_status": "complete",
                    "partial_evidence": False,
                    "relation_source": "dgekt_offline_explainability",
                    "graph_source": "dgekt_dual_graph_offline_scorer",
                    "scorer_name": row.get("scorer_name") or self._scorer_name(),
                    "scorer_version": row.get("scorer_version") or self._scorer_version(),
                }
            )
        return sorted(paths, key=lambda item: (item["rank"], item["path_id"]))

    def _key_history(
        self,
        sample_id: str,
        gaps: list[OfflineEvidenceGap],
    ) -> list[dict[str, Any]]:
        rows = self._rows_for_sample("key_history.csv", sample_id)
        history = []
        for row in rows:
            parsed = self._parse_row(
                row,
                filename="key_history.csv",
                sample_id=sample_id,
                gaps=gaps,
                integer_fields=[
                    "history_rank",
                    "target_question_id",
                    "target_concept_id",
                    "history_question_id",
                    "history_concept_id",
                    "history_position",
                ],
                float_fields=["influence_score"],
            )
            if parsed is None:
                continue
            history.append(
                {
                    "rank": parsed["history_rank"],
                    "xes3g5m_question_id": parsed["history_question_id"],
                    "question_id": _optional_str(row.get("history_canonical_question_id")),
                    "xes3g5m_concept_id": parsed["history_concept_id"],
                    "concept_id": _optional_str(row.get("history_canonical_concept_id")),
                    "answer": row.get("history_answer"),
                    "is_correct": _parse_bool(row.get("history_is_correct")),
                    "history_position": parsed["history_position"],
                    "influence_score": parsed["influence_score"],
                    "target_xes3g5m_question_id": parsed["target_question_id"],
                    "target_question_id": _optional_str(row.get("canonical_target_question_id")),
                    "target_xes3g5m_concept_id": parsed["target_concept_id"],
                    "target_concept_id": _optional_str(row.get("canonical_target_concept_id")),
                    "readable_summary": row.get("readable_summary")
                    or (
                        f"XES3G5M Q{parsed['history_question_id']} | "
                        f"{'correct' if _parse_bool(row.get('history_is_correct')) else 'incorrect'}"
                    ),
                    "influence_source": "dgekt_offline_key_history",
                }
            )
        return sorted(history, key=lambda item: (item["rank"], item["xes3g5m_question_id"]))

    def _weak_concepts(
        self,
        sample_id: str,
        gaps: list[OfflineEvidenceGap],
    ) -> list[dict[str, Any]]:
        rows = self._rows_for_sample("weak_concepts.csv", sample_id)
        concepts = []
        for row in rows:
            parsed = self._parse_row(
                row,
                filename="weak_concepts.csv",
                sample_id=sample_id,
                gaps=gaps,
                integer_fields=[
                    "target_question_id",
                    "target_concept_id",
                    "weak_concept_id",
                ],
                float_fields=["mastery_score", "risk_score"],
            )
            if parsed is None:
                continue
            concepts.append(
                {
                    "xes3g5m_concept_id": parsed["weak_concept_id"],
                    "concept_id": _optional_str(row.get("weak_canonical_concept_id")),
                    "concept_name": row.get("concept_name"),
                    "mastery": parsed["mastery_score"],
                    "risk_score": parsed["risk_score"],
                    "hit": _parse_bool(row.get("hit")),
                    "path_ids": _parse_json_or_pipe(row.get("path_ids")),
                    "evidence_source": row.get("evidence_source") or "dgekt_offline_weak_concepts",
                }
            )
        return sorted(concepts, key=lambda item: (item["xes3g5m_concept_id"], item["concept_id"] or ""))

    def _path_ablation(
        self,
        sample_id: str,
        gaps: list[OfflineEvidenceGap],
    ) -> list[dict[str, Any]]:
        rows = self._rows_for_sample("path_ablation.csv", sample_id)
        ablations = []
        for row in rows:
            parsed = self._parse_row(
                row,
                filename="path_ablation.csv",
                sample_id=sample_id,
                gaps=gaps,
                integer_fields=["target_question_id", "target_concept_id", "k"],
                float_fields=[
                    "original_prediction",
                    "ablated_prediction",
                    "impact",
                    "comprehensiveness",
                ],
            )
            if parsed is None:
                continue
            ablations.append(
                {
                    "strategy": row.get("strategy"),
                    "k": parsed["k"],
                    "path_ids": _parse_json_or_pipe(row.get("path_ids")),
                    "original_prediction": parsed["original_prediction"],
                    "ablated_prediction": parsed["ablated_prediction"],
                    "impact": parsed["impact"],
                    "comprehensiveness": parsed["comprehensiveness"],
                    "warnings": _parse_json_or_pipe(row.get("warnings")),
                    "evidence_source": "dgekt_offline_path_ablation",
                }
            )
        return sorted(
            ablations,
            key=lambda item: (str(item.get("strategy") or ""), int(item.get("k") or 0)),
        )

    def _rows_for_sample(self, filename: str, sample_id: str) -> list[dict[str, str]]:
        return [row for row in self.rows.get(filename, []) if row.get("sample_id") == sample_id]

    def _parse_row(
        self,
        row: dict[str, str],
        *,
        filename: str,
        sample_id: str,
        gaps: list[OfflineEvidenceGap],
        integer_fields: list[str],
        float_fields: list[str],
    ) -> dict[str, Any] | None:
        required = REQUIRED_FILES[filename]
        missing_values = sorted(field for field in required if row.get(field) in (None, ""))
        if missing_values:
            gaps.append(
                OfflineEvidenceGap(
                    category="malformed_row",
                    reason_code=f"{Path(filename).stem}_required_value_missing",
                    severity="error",
                    message=(
                        f"{filename} sample {sample_id} has empty required value(s): "
                        f"{', '.join(missing_values)}."
                    ),
                    actionable_hint="补齐 required value，避免 offline evidence 行语义不完整。",
                    source_ref=filename,
                    sample_id=sample_id,
                    details={"missing_values": missing_values},
                )
            )
            return None

        parsed: dict[str, Any] = {}
        for field in integer_fields:
            try:
                parsed[field] = int(str(row[field]))
            except (KeyError, TypeError, ValueError):
                gaps.append(
                    _invalid_numeric_gap(filename, sample_id, field, row.get(field))
                )
                return None
        for field in float_fields:
            try:
                parsed[field] = float(str(row[field]))
            except (KeyError, TypeError, ValueError):
                gaps.append(
                    _invalid_numeric_gap(filename, sample_id, field, row.get(field))
                )
                return None
        return parsed

    def _mapped_teaching_content(
        self,
        case: OfflineEvidenceCase,
        *,
        fallback: dict[str, Any] | None,
    ) -> dict[str, Any]:
        mapping = (
            self.mapping_repository.get_by_xes3g5m_question_id(case.target_question_id)
            if self.mapping_repository is not None
            else None
        )
        if mapping is not None:
            return {
                "question_id": mapping.question_id,
                "concept_id": mapping.concept_id,
                "concept_name": mapping.concept_name,
                "teaching_type": mapping.teaching_type,
                "xes3g5m_question_id": mapping.xes3g5m_question_id,
                "xes3g5m_concept_id": mapping.xes3g5m_concept_id,
                "mapping_status": "canonical_mapping_repository",
                "relation_source": "dgekt_offline_explainability",
            }
        return {
            **(fallback or {}),
            "question_id": (fallback or {}).get("question_id") or case.canonical_question_id,
            "concept_id": (fallback or {}).get("concept_id") or case.canonical_concept_id,
            "xes3g5m_question_id": case.target_question_id,
            "xes3g5m_concept_id": case.target_concept_id,
            "mapping_status": (fallback or {}).get("mapping_status") or "offline_case_metadata",
            "relation_source": "dgekt_offline_explainability",
        }

    def _canonical_mapping(
        self,
        case: OfflineEvidenceCase,
        *,
        fallback: dict[str, Any] | None,
    ) -> dict[str, Any]:
        mapping = (
            self.mapping_repository.get_by_xes3g5m_question_id(case.target_question_id)
            if self.mapping_repository is not None
            else None
        )
        if mapping is not None:
            return {
                "question_id": mapping.question_id,
                "concept_id": mapping.concept_id,
                "concept_name": mapping.concept_name,
                "teaching_type": mapping.teaching_type,
                "xes3g5m_question_id": mapping.xes3g5m_question_id,
                "xes3g5m_concept_id": mapping.xes3g5m_concept_id,
                "kc_routes_reference": mapping.kc_routes_reference.model_dump(),
                "source": mapping.source_provenance.source,
                "mapping_status": "canonical_mapping_repository",
            }
        return {
            **(fallback or {}),
            "xes3g5m_question_id": case.target_question_id,
            "xes3g5m_concept_id": case.target_concept_id,
            "question_id": case.canonical_question_id,
            "concept_id": case.canonical_concept_id,
            "source": "offline_case_metadata",
        }

    def _gap_evidence(
        self,
        *,
        status: str,
        target_question_id: str,
        target_xes3g5m_question_id: int | None,
        target_xes3g5m_concept_id: int | None,
        prediction_probability: float | None,
        weak_concepts: list[dict[str, Any]],
        gaps: list[OfflineEvidenceGap],
        sample_id: str | None = None,
        fallback_mapped_teaching_content: dict[str, Any] | None = None,
        fallback_canonical_mapping: dict[str, Any] | None = None,
    ) -> AttributionEvidence:
        reason = gaps[0].message if gaps else "Offline DGEKT evidence is unavailable."
        return AttributionEvidence(
            target_question_id=target_question_id,
            target_concept_id=(fallback_mapped_teaching_content or {}).get("concept_id"),
            target_xes3g5m_question_id=target_xes3g5m_question_id,
            target_xes3g5m_concept_id=target_xes3g5m_concept_id,
            prediction_probability=prediction_probability,
            evidence_status=status,
            evidence_source="offline",
            partial_evidence=True,
            partial_evidence_reason=reason,
            raw_model_target={
                "sample_id": sample_id,
                "dataset": self.diagnosis_payload.get("dataset", "xes3g5m"),
                "target_question_id": target_xes3g5m_question_id,
                "target_concept_id": target_xes3g5m_concept_id,
                "mapping_status": status,
                "model_vocabulary": "DGEKT XES3G5M question/concept ids",
            },
            mapped_teaching_content=fallback_mapped_teaching_content or {},
            canonical_mapping=fallback_canonical_mapping or {},
            scorer=self._scorer_metadata(
                evidence_status=status,
                matching_method="unavailable",
                sample_id=sample_id,
                checkpoint_provenance={},
                gaps=gaps,
            ),
            provenance={
                "artifact_dir": str(self.artifact_dir),
                "source": "dgekt_offline_evidence_adapter",
                "offline_path_scorer_available": False,
                "schema_version": self.diagnosis_payload.get("schema_version"),
            },
            top_paths=[],
            key_history=[],
            weak_concepts=weak_concepts,
            path_ablation=[],
            evidence_gaps=[gap.as_trace_gap() for gap in gaps],
        )

    def _scorer_metadata(
        self,
        *,
        evidence_status: str,
        matching_method: str,
        sample_id: str | None,
        checkpoint_provenance: dict[str, Any],
        gaps: list[OfflineEvidenceGap] | None = None,
    ) -> dict[str, Any]:
        return {
            "name": self._scorer_name(),
            "version": self._scorer_version(),
            "engine": "dgekt",
            "dataset": self.diagnosis_payload.get("dataset", "xes3g5m"),
            "evidence_status": evidence_status,
            "evidence_source": "offline",
            "partial_evidence": evidence_status != "complete",
            "matching_method": matching_method,
            "sample_id": sample_id,
            "run_id": self.scorer.get("run_id"),
            "generated_at": self.scorer.get("generated_at"),
            "checkpoint_provenance": checkpoint_provenance or self.checkpoint_provenance,
            "gap_categories": [gap.category for gap in gaps or []],
        }

    def _provenance(
        self,
        case: OfflineEvidenceCase,
        checkpoint_provenance: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "artifact_dir": str(self.artifact_dir),
            "source": "dgekt_offline_evidence_adapter",
            "offline_path_scorer_available": True,
            "schema_version": self.diagnosis_payload.get(
                "schema_version",
                OFFLINE_EVIDENCE_SCHEMA_VERSION,
            ),
            "sample_id": case.sample_id,
            "case_provenance": case.raw.get("provenance", {}),
            "artifact_provenance": self.artifact_provenance,
            "checkpoint_provenance": checkpoint_provenance or self.checkpoint_provenance,
            "files": sorted([*REQUIRED_FILES.keys(), "diagnosis_cases.json"]),
        }

    def _scorer_name(self) -> str:
        return str(self.scorer.get("name") or OFFLINE_SCORER_DEFAULT_NAME)

    def _scorer_version(self) -> str:
        return str(self.scorer.get("version") or OFFLINE_SCORER_DEFAULT_VERSION)


def _status_for_load_gaps(gaps: list[OfflineEvidenceGap]) -> str:
    categories = {gap.category for gap in gaps}
    if "missing_artifact" in categories:
        return "unavailable"
    return "invalid"


def _invalid_numeric_gap(
    filename: str,
    sample_id: str,
    field: str,
    value: Any,
) -> OfflineEvidenceGap:
    return OfflineEvidenceGap(
        category="invalid_numeric_value",
        reason_code=f"{Path(filename).stem}_invalid_numeric_value",
        severity="error",
        message=f"{filename} sample {sample_id} has invalid numeric value for {field}: {value!r}.",
        actionable_hint="修复 CSV 数值列，确保 rank、score、risk、mastery 等字段可解析为数字。",
        source_ref=filename,
        sample_id=sample_id,
        details={"field": field, "value": value},
    )


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "correct"}


def _parse_json_or_pipe(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    text = str(value).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [item.strip() for item in text.split("|") if item.strip()]
    if isinstance(parsed, list):
        return parsed
    return [parsed]


def _resolve_project_path(path: str | Path) -> Path:
    resolved = Path(path)
    if resolved.is_absolute() or resolved.exists():
        return resolved
    return Path(__file__).resolve().parents[3] / resolved
