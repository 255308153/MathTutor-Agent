from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.importing.assist2017_artifacts import (
    CONTENT_SCHEMA_VERSION,
    COVERAGE_SCHEMA_VERSION,
    RAG_SCHEMA_VERSION,
    SMOKE_SCHEMA_VERSION,
    Assist2017BuildError,
    ContentImportArtifact,
    CoverageReportArtifact,
    RAGDocumentArtifact,
    SmokeDatasetArtifact,
    build_assist2017_import_artifacts,
)
from backend.app.mapping.assist2017_mapping import CanonicalMappingArtifact


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROWS = ROOT / "data" / "import" / "assist2017_source.fixture.csv"
Q_MATRIX = ROOT / "data" / "mapping" / "assist2017_q_matrix.fixture.csv"


def test_builds_v15_artifact_schemas_from_realistic_fixture(tmp_path: Path) -> None:
    output_dir = tmp_path / "assist2017-artifacts"

    artifacts = build_assist2017_import_artifacts(
        source_rows_path=SOURCE_ROWS,
        q_matrix_path=Q_MATRIX,
        output_dir=output_dir,
        generated_at="2026-07-09T00:00:00+00:00",
    )

    assert CanonicalMappingArtifact.model_validate(artifacts.mapping.model_dump())
    assert ContentImportArtifact.model_validate(artifacts.content.model_dump())
    assert RAGDocumentArtifact.model_validate(artifacts.rag.model_dump())
    assert CoverageReportArtifact.model_validate(artifacts.coverage.model_dump())
    assert SmokeDatasetArtifact.model_validate(artifacts.smoke.model_dump())
    assert artifacts.content.schema_version == CONTENT_SCHEMA_VERSION
    assert artifacts.rag.schema_version == RAG_SCHEMA_VERSION
    assert artifacts.coverage.schema_version == COVERAGE_SCHEMA_VERSION
    assert artifacts.smoke.schema_version == SMOKE_SCHEMA_VERSION

    assert (output_dir / "canonical_mapping.json").is_file()
    assert (output_dir / "content_import.json").is_file()
    assert (output_dir / "rag_documents.json").is_file()
    assert (output_dir / "coverage_report.json").is_file()
    assert (output_dir / "smoke_dataset.json").is_file()
    assert artifacts.content.metadata.row_counts["source_rows"] == 3
    assert artifacts.content.metadata.row_counts["q_matrix_questions"] == 6
    assert artifacts.content.metadata.source_paths["source_rows"].endswith(
        "data/import/assist2017_source.fixture.csv"
    )
    assert artifacts.content.metadata.coverage_summary["mapping"]["mapped_question_count"] == 3


def test_canonical_ids_are_stable_when_source_order_changes(tmp_path: Path) -> None:
    shuffled_source = tmp_path / "source_shuffled.csv"
    rows = list(csv.DictReader(SOURCE_ROWS.open("r", encoding="utf-8-sig", newline="")))
    with shuffled_source.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(reversed(rows))

    original = build_assist2017_import_artifacts(
        source_rows_path=SOURCE_ROWS,
        q_matrix_path=Q_MATRIX,
        generated_at="fixed",
    )
    shuffled = build_assist2017_import_artifacts(
        source_rows_path=shuffled_source,
        q_matrix_path=Q_MATRIX,
        generated_at="fixed",
    )

    assert [question.question_id for question in original.mapping.questions] == [
        "q_assist2017_000001",
        "q_assist2017_000003",
        "q_assist2017_000005",
    ]
    assert [question.question_id for question in original.mapping.questions] == [
        question.question_id for question in shuffled.mapping.questions
    ]
    assert [concept.concept_id for concept in original.mapping.concepts] == [
        concept.concept_id for concept in shuffled.mapping.concepts
    ]


def test_coverage_reports_mapping_content_rag_and_q_matrix_gaps() -> None:
    artifacts = build_assist2017_import_artifacts(
        source_rows_path=SOURCE_ROWS,
        q_matrix_path=Q_MATRIX,
        generated_at="fixed",
    )
    summary = artifacts.coverage.summary
    gaps = artifacts.coverage.gaps

    assert summary["mapping"]["mapped_question_count"] == 3
    assert summary["mapping"]["unmapped_question_count"] == 3
    assert summary["mapping"]["unmapped_concept_count"] == 1
    assert summary["content"]["missing_teaching_content_count"] == 1
    assert summary["rag"]["missing_rag_doc_count"] == 1
    assert summary["q_matrix"]["mismatch_count"] == 0
    assert {
        gap.reason_code
        for gap in gaps
    }.issuperset(
        {
            "q_matrix_row_without_source_question",
            "q_matrix_concept_without_source_concept",
            "essential_teaching_field_missing",
            "expected_rag_doc_not_generated",
        }
    )
    missing_content = next(
        gap for gap in gaps if gap.reason_code == "essential_teaching_field_missing"
    )
    assert missing_content.canonical_question_id == "q_assist2017_000005"
    assert missing_content.provenance["missing_fields"] == ["explanation"]


def test_cli_writes_artifacts_and_prints_summary(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli-output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.importing.build_assist2017_artifacts",
            "--source-rows",
            str(SOURCE_ROWS),
            "--q-matrix",
            str(Q_MATRIX),
            "--output-dir",
            str(output_dir),
            "--generated-at",
            "2026-07-09T00:00:00+00:00",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["coverage_summary"]["mapping"]["mapped_question_count"] == 3
    assert json.loads((output_dir / "coverage_report.json").read_text(encoding="utf-8"))[
        "schema_version"
    ] == COVERAGE_SCHEMA_VERSION


def test_missing_file_and_malformed_row_fail_with_actionable_categories(
    tmp_path: Path,
) -> None:
    with pytest.raises(Assist2017BuildError) as missing_file:
        build_assist2017_import_artifacts(
            source_rows_path=tmp_path / "missing.csv",
            q_matrix_path=Q_MATRIX,
            generated_at="fixed",
        )
    assert missing_file.value.issues[0].category == "missing_file"
    assert missing_file.value.issues[0].reason_code == "source_rows_not_found"

    malformed = tmp_path / "malformed.csv"
    malformed.write_text(
        SOURCE_ROWS.read_text(encoding="utf-8").replace("0.35", "not-a-number", 1),
        encoding="utf-8",
    )
    with pytest.raises(Assist2017BuildError) as malformed_row:
        build_assist2017_import_artifacts(
            source_rows_path=malformed,
            q_matrix_path=Q_MATRIX,
            generated_at="fixed",
        )
    assert malformed_row.value.issues[0].category == "malformed_row"
    assert malformed_row.value.issues[0].reason_code == "invalid_source_row"


def test_q_matrix_mismatch_fails_by_default_and_can_be_diagnosed(
    tmp_path: Path,
) -> None:
    mismatched_source = tmp_path / "mismatched.csv"
    mismatched_source.write_text(
        SOURCE_ROWS.read_text(encoding="utf-8").replace(
            "3,2,异分母分数加法", "3,4,异分母分数加法", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(Assist2017BuildError) as mismatch:
        build_assist2017_import_artifacts(
            source_rows_path=mismatched_source,
            q_matrix_path=Q_MATRIX,
            generated_at="fixed",
        )
    assert mismatch.value.issues[0].category == "q_matrix_mismatch"
    assert mismatch.value.issues[0].reason_code == "concept_not_in_q_matrix_row"

    diagnostic = build_assist2017_import_artifacts(
        source_rows_path=mismatched_source,
        q_matrix_path=Q_MATRIX,
        generated_at="fixed",
        fail_on_errors=False,
    )
    assert diagnostic.coverage.summary["q_matrix"]["mismatch_count"] == 1
    assert any(gap.category == "q_matrix_mismatch" for gap in diagnostic.coverage.gaps)

