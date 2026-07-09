from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

import pytest

from backend.app.kt.offline_evidence import DGEKTOfflineEvidenceAdapter


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "data" / "dgekt" / "offline_evidence_fixture"

CHECKPOINT_PROVENANCE = {
    "dataset": "assist2017",
    "checkpoint_id": "dgekt-assist2017-fixture-epoch26",
    "epoch": 26,
    "auc": 0.7866464407565317,
    "acc": 0.728796544573157,
}


def test_offline_evidence_fixture_returns_complete_payload() -> None:
    adapter = DGEKTOfflineEvidenceAdapter(FIXTURE_DIR)

    evidence = adapter.explain_prediction(
        dataset="assist2017",
        student_id="student-dgekt-offline-fixture",
        target_question_id="q_frac_001",
        target_assist2017_question_id=3,
        target_assist2017_concept_id=2,
        prediction_probability=0.2,
        authoritative_weak_concepts=[{"concept_id": "c_assist2017_0002", "mastery": 0.2}],
        checkpoint_provenance=CHECKPOINT_PROVENANCE,
    )

    assert evidence.evidence_status == "complete"
    assert evidence.evidence_source == "offline"
    assert evidence.partial_evidence is False
    assert evidence.scorer["name"] == "dgekt_offline_path_scorer"
    assert evidence.scorer["matching_method"] == "student_target_exact"
    assert evidence.provenance["offline_path_scorer_available"] is True
    assert evidence.raw_model_target["sample_id"] == "fixture-s1-t2-q3"
    assert evidence.raw_model_target["canonical_question_id"] == "q_frac_001"
    assert evidence.mapped_teaching_content["question_id"] == "q_frac_001"
    assert evidence.mapped_teaching_content["concept_id"] == "c_fraction_addition"
    assert evidence.canonical_mapping["assist2017_question_id"] == 3

    top_path = evidence.top_paths[0]
    assert top_path["path_id"] == "path-fixture-history-q3"
    assert top_path["rank"] == 1
    assert top_path["path_nodes"] == ["Q3:incorrect", "concept:2", "Q3:target"]
    assert top_path["path_score"] == 0.842
    assert top_path["risk_score"] == 0.8
    assert top_path["mastery_score"] == 0.2
    assert top_path["graph_relation_strength"] == 0.88
    assert top_path["relation_strength"] == 0.91

    assert evidence.key_history[0]["assist2017_question_id"] == 3
    assert evidence.key_history[0]["is_correct"] is False
    assert evidence.weak_concepts[0]["concept_id"] == "c_fraction_addition"
    assert evidence.path_ablation[0]["impact"] == 0.16
    assert evidence.path_ablation[0]["path_ids"] == ["path-fixture-history-q3"]
    assert evidence.evidence_gaps == []


def test_offline_evidence_normalization_is_deterministic_for_csv_order(
    tmp_path: Path,
) -> None:
    first_dir = _copy_fixture(tmp_path / "first")
    second_dir = _copy_fixture(tmp_path / "second")
    _reverse_csv_rows(second_dir / "attribution_paths.csv")
    _reverse_csv_rows(second_dir / "key_history.csv")

    first = _complete_evidence(first_dir).model_dump()
    second = _complete_evidence(second_dir).model_dump()

    assert first["top_paths"] == second["top_paths"]
    assert first["key_history"] == second["key_history"]
    assert first["weak_concepts"] == second["weak_concepts"]
    assert first["path_ablation"] == second["path_ablation"]


def test_offline_evidence_reports_missing_file_gap(tmp_path: Path) -> None:
    artifact_dir = _copy_fixture(tmp_path)
    (artifact_dir / "key_history.csv").unlink()

    evidence = _complete_evidence(artifact_dir)

    assert evidence.evidence_status == "unavailable"
    assert evidence.partial_evidence is True
    assert evidence.evidence_gaps[0]["category"] == "missing_artifact"
    assert "key_history.csv" in evidence.evidence_gaps[0]["reason"]


def test_offline_evidence_reports_missing_column_gap(tmp_path: Path) -> None:
    artifact_dir = _copy_fixture(tmp_path)
    _drop_csv_column(artifact_dir / "attribution_paths.csv", "path_score")

    evidence = _complete_evidence(artifact_dir)

    assert evidence.evidence_status == "invalid"
    assert evidence.evidence_gaps[0]["category"] == "missing_column"
    assert "path_score" in evidence.evidence_gaps[0]["details"]["missing_columns"]


def test_offline_evidence_reports_malformed_row_gap(tmp_path: Path) -> None:
    artifact_dir = _copy_fixture(tmp_path)
    _rewrite_csv_value(
        artifact_dir / "weak_concepts.csv",
        row_index=0,
        column="target_question_id",
        value="",
    )

    evidence = _complete_evidence(artifact_dir)

    assert evidence.evidence_status == "invalid"
    assert evidence.evidence_gaps[0]["category"] == "malformed_row"
    assert "target_question_id" in evidence.evidence_gaps[0]["details"]["missing_values"]


def test_offline_evidence_reports_invalid_numeric_gap(tmp_path: Path) -> None:
    artifact_dir = _copy_fixture(tmp_path)
    _rewrite_csv_value(
        artifact_dir / "path_ablation.csv",
        row_index=0,
        column="impact",
        value="not-a-number",
    )

    evidence = _complete_evidence(artifact_dir)

    assert evidence.evidence_status == "invalid"
    assert evidence.evidence_gaps[0]["category"] == "invalid_numeric_value"
    assert evidence.evidence_gaps[0]["details"]["field"] == "impact"


def test_offline_evidence_reports_duplicate_sample_gap(tmp_path: Path) -> None:
    artifact_dir = _copy_fixture(tmp_path)
    diagnosis_path = artifact_dir / "diagnosis_cases.json"
    payload = json.loads(diagnosis_path.read_text(encoding="utf-8"))
    payload["cases"].append(dict(payload["cases"][0]))
    diagnosis_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    evidence = _complete_evidence(artifact_dir)

    assert evidence.evidence_status == "invalid"
    assert evidence.evidence_gaps[0]["category"] == "duplicate_sample"


def test_offline_evidence_reports_target_not_found_gap() -> None:
    adapter = DGEKTOfflineEvidenceAdapter(FIXTURE_DIR)

    evidence = adapter.explain_prediction(
        dataset="assist2017",
        student_id="student-dgekt-offline-fixture",
        target_question_id="q_eq_001",
        target_assist2017_question_id=5,
        target_assist2017_concept_id=3,
        prediction_probability=0.2,
        authoritative_weak_concepts=[],
        checkpoint_provenance=CHECKPOINT_PROVENANCE,
    )

    assert evidence.evidence_status == "unavailable"
    assert evidence.evidence_gaps[0]["category"] == "target_not_found"


def test_offline_evidence_does_not_reuse_other_student_case() -> None:
    adapter = DGEKTOfflineEvidenceAdapter(FIXTURE_DIR)

    evidence = adapter.explain_prediction(
        dataset="assist2017",
        student_id="another-student",
        target_question_id="q_frac_001",
        target_assist2017_question_id=3,
        target_assist2017_concept_id=2,
        prediction_probability=0.2,
        authoritative_weak_concepts=[],
        checkpoint_provenance=CHECKPOINT_PROVENANCE,
    )

    assert evidence.evidence_status == "unavailable"
    assert evidence.evidence_gaps[0]["category"] == "target_not_found"


def test_offline_evidence_reports_checkpoint_provenance_mismatch() -> None:
    adapter = DGEKTOfflineEvidenceAdapter(FIXTURE_DIR)

    evidence = adapter.explain_prediction(
        dataset="assist2017",
        student_id="student-dgekt-offline-fixture",
        target_question_id="q_frac_001",
        target_assist2017_question_id=3,
        target_assist2017_concept_id=2,
        prediction_probability=0.2,
        authoritative_weak_concepts=[],
        checkpoint_provenance=CHECKPOINT_PROVENANCE | {"checkpoint_id": "other-checkpoint"},
    )

    assert evidence.evidence_status == "invalid"
    assert evidence.evidence_gaps[0]["category"] == "checkpoint_provenance_mismatch"
    assert "checkpoint_id" in evidence.evidence_gaps[0]["details"]["mismatches"]


def test_offline_evidence_reports_non_numeric_checkpoint_metric_mismatch() -> None:
    adapter = DGEKTOfflineEvidenceAdapter(FIXTURE_DIR)

    evidence = adapter.explain_prediction(
        dataset="assist2017",
        student_id="student-dgekt-offline-fixture",
        target_question_id="q_frac_001",
        target_assist2017_question_id=3,
        target_assist2017_concept_id=2,
        prediction_probability=0.2,
        authoritative_weak_concepts=[],
        checkpoint_provenance=CHECKPOINT_PROVENANCE | {"auc": "unknown"},
    )

    assert evidence.evidence_status == "invalid"
    assert evidence.evidence_gaps[0]["category"] == "checkpoint_provenance_mismatch"
    assert "auc" in evidence.evidence_gaps[0]["details"]["mismatches"]


def test_offline_evidence_reports_canonical_mapping_mismatch(tmp_path: Path) -> None:
    artifact_dir = _copy_fixture(tmp_path)
    diagnosis_path = artifact_dir / "diagnosis_cases.json"
    payload = json.loads(diagnosis_path.read_text(encoding="utf-8"))
    payload["cases"][0]["canonical_question_id"] = "q_wrong_mapping"
    diagnosis_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    evidence = _complete_evidence(artifact_dir)

    assert evidence.evidence_status == "invalid"
    assert evidence.evidence_gaps[0]["category"] == "canonical_mapping_mismatch"
    assert "mapping_repository_question_id" in evidence.evidence_gaps[0]["details"]["mismatches"]


@pytest.mark.skipif(
    os.getenv("MATHTUTOR_RUN_DGEKT_OFFLINE_EVIDENCE_SMOKE") != "1",
    reason=(
        "Set MATHTUTOR_RUN_DGEKT_OFFLINE_EVIDENCE_SMOKE=1 and "
        "MATHTUTOR_DGEKT_OFFLINE_EVIDENCE_DIR to validate local full offline outputs."
    ),
)
def test_dgekt_real_offline_evidence_outputs_smoke() -> None:
    artifact_dir = os.getenv("MATHTUTOR_DGEKT_OFFLINE_EVIDENCE_DIR")
    assert artifact_dir, (
        "MATHTUTOR_DGEKT_OFFLINE_EVIDENCE_DIR must point to local full DGEKT "
        "offline explainability outputs when the smoke is enabled."
    )
    adapter = DGEKTOfflineEvidenceAdapter(
        artifact_dir,
        canonical_mapping_path=os.getenv("MATHTUTOR_DGEKT_CANONICAL_MAPPING_PATH", ""),
    )

    assert adapter.load_gaps == []
    assert adapter.cases

    case = sorted(adapter.cases.values(), key=lambda item: item.sample_id)[0]
    checkpoint_provenance = {
        **adapter.checkpoint_provenance,
        "dataset": case.dataset,
        "checkpoint_id": case.checkpoint_id
        or adapter.checkpoint_provenance.get("checkpoint_id"),
    }

    evidence = adapter.explain_prediction(
        dataset=case.dataset,
        student_id=case.student_id or "",
        target_question_id=case.canonical_question_id or f"assist2017:{case.target_question_id}",
        target_assist2017_question_id=case.target_question_id,
        target_assist2017_concept_id=case.target_concept_id,
        prediction_probability=case.prediction_probability,
        authoritative_weak_concepts=[],
        checkpoint_provenance=checkpoint_provenance,
    )

    assert evidence.evidence_status == "complete"
    assert evidence.evidence_source == "offline"
    assert evidence.scorer["name"]
    assert evidence.top_paths
    assert evidence.key_history


def _complete_evidence(artifact_dir: Path):
    return DGEKTOfflineEvidenceAdapter(artifact_dir).explain_prediction(
        dataset="assist2017",
        student_id="student-dgekt-offline-fixture",
        target_question_id="q_frac_001",
        target_assist2017_question_id=3,
        target_assist2017_concept_id=2,
        prediction_probability=0.2,
        authoritative_weak_concepts=[],
        checkpoint_provenance=CHECKPOINT_PROVENANCE,
    )


def _copy_fixture(destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(FIXTURE_DIR, destination)
    return destination


def _reverse_csv_rows(path: Path) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reversed(rows))


def _drop_csv_column(path: Path, column: str) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        fieldnames = [name for name in list(reader.fieldnames or []) if name != column]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row.pop(column, None)
            writer.writerow(row)


def _rewrite_csv_value(path: Path, *, row_index: int, column: str, value: str) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    rows[row_index][column] = value
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
