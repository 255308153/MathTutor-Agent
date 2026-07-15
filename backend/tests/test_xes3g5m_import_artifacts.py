from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.importing.xes3g5m_artifacts import (
    CONTENT_SCHEMA_VERSION,
    COVERAGE_SCHEMA_VERSION,
    RAG_SCHEMA_VERSION,
    SMOKE_SCHEMA_VERSION,
    Assist2017BuildError,
    ContentImportArtifact,
    CoverageReportArtifact,
    RAGDocumentArtifact,
    SmokeDatasetArtifact,
    build_xes3g5m_import_artifacts,
)
from backend.app.mapping.xes3g5m_mapping import CanonicalMappingArtifact


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROWS = ROOT / "data" / "import" / "xes3g5m_source.fixture.csv"
Q_MATRIX = ROOT / "data" / "mapping" / "xes3g5m_kc_routes.fixture.csv"


def test_builds_v15_artifact_schemas_from_realistic_fixture(tmp_path: Path) -> None:
    output_dir = tmp_path / "xes3g5m-artifacts"

    artifacts = build_xes3g5m_import_artifacts(
        source_rows_path=SOURCE_ROWS,
        kc_routes_path=Q_MATRIX,
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
    assert artifacts.content.metadata.row_counts["kc_routes_questions"] == 6
    assert artifacts.content.metadata.source_paths["source_rows"].endswith(
        "data/import/xes3g5m_source.fixture.csv"
    )
    assert artifacts.content.metadata.coverage_summary["mapping"]["mapped_question_count"] == 3


def test_canonical_ids_are_stable_when_source_order_changes(tmp_path: Path) -> None:
    shuffled_source = tmp_path / "source_shuffled.csv"
    rows = list(csv.DictReader(SOURCE_ROWS.open("r", encoding="utf-8-sig", newline="")))
    with shuffled_source.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(reversed(rows))

    original = build_xes3g5m_import_artifacts(
        source_rows_path=SOURCE_ROWS,
        kc_routes_path=Q_MATRIX,
        generated_at="fixed",
    )
    shuffled = build_xes3g5m_import_artifacts(
        source_rows_path=shuffled_source,
        kc_routes_path=Q_MATRIX,
        generated_at="fixed",
    )

    assert [question.question_id for question in original.mapping.questions] == [
        "q_xes3g5m_000001",
        "q_xes3g5m_000003",
        "q_xes3g5m_000005",
    ]
    assert [question.question_id for question in original.mapping.questions] == [
        question.question_id for question in shuffled.mapping.questions
    ]
    assert [concept.concept_id for concept in original.mapping.concepts] == [
        concept.concept_id for concept in shuffled.mapping.concepts
    ]


def test_coverage_reports_mapping_content_rag_and_kc_routes_gaps() -> None:
    artifacts = build_xes3g5m_import_artifacts(
        source_rows_path=SOURCE_ROWS,
        kc_routes_path=Q_MATRIX,
        generated_at="fixed",
    )
    summary = artifacts.coverage.summary
    gaps = artifacts.coverage.gaps

    assert summary["mapping"]["mapped_question_count"] == 3
    assert summary["mapping"]["unmapped_question_count"] == 3
    assert summary["mapping"]["unmapped_question_ids"] == [
        "q_xes3g5m_000002",
        "q_xes3g5m_000004",
        "q_xes3g5m_000006",
    ]
    assert summary["mapping"]["unmapped_concept_count"] == 1
    assert summary["mapping"]["unmapped_concept_ids"] == ["c_xes3g5m_0004"]
    assert summary["content"]["missing_teaching_content_count"] == 1
    assert summary["content"]["missing_teaching_content"][0]["canonical_question_id"] == (
        "q_xes3g5m_000005"
    )
    assert summary["content"]["missing_teaching_content"][0]["missing_fields"] == [
        "explanation"
    ]
    assert summary["rag"]["missing_rag_doc_count"] == 1
    assert summary["rag"]["missing_rag_docs"][0]["doc_id"] == (
        "rag_xes3g5m_q000005_question_explanation"
    )
    assert summary["kc_routes"]["mismatch_count"] == 0
    assert {
        gap.reason_code
        for gap in gaps
    }.issuperset(
        {
            "kc_routes_row_without_source_question",
            "kc_routes_concept_without_source_concept",
            "essential_teaching_field_missing",
            "expected_rag_doc_not_generated",
        }
    )
    missing_content = next(
        gap for gap in gaps if gap.reason_code == "essential_teaching_field_missing"
    )
    assert missing_content.canonical_question_id == "q_xes3g5m_000005"
    assert missing_content.provenance["missing_fields"] == ["explanation"]
    assert missing_content.provenance["missing_reason_codes"] == ["missing_explanation"]


def test_coverage_summary_keeps_mapping_content_rag_and_kc_routes_gap_details(
    tmp_path: Path,
) -> None:
    mismatched_source = tmp_path / "mismatched.csv"
    mismatched_source.write_text(
        SOURCE_ROWS.read_text(encoding="utf-8").replace(
            "3,2,异分母分数加法", "3,4,异分母分数加法", 1
        ),
        encoding="utf-8",
    )

    diagnostic = build_xes3g5m_import_artifacts(
        source_rows_path=mismatched_source,
        kc_routes_path=Q_MATRIX,
        generated_at="fixed",
        fail_on_errors=False,
    )
    summary = diagnostic.coverage.summary

    assert summary["mapping"]["mapped_question_ids"] == [
        "q_xes3g5m_000001",
        "q_xes3g5m_000005",
    ]
    assert summary["mapping"]["unmapped_question_ids"] == [
        "q_xes3g5m_000002",
        "q_xes3g5m_000003",
        "q_xes3g5m_000004",
        "q_xes3g5m_000006",
    ]
    assert summary["kc_routes"]["mismatch_count"] == 1
    assert summary["kc_routes"]["mismatches"][0]["reason_code"] == (
        "concept_not_in_kc_routes_row"
    )
    assert summary["kc_routes"]["mismatches"][0]["canonical_question_id"] == (
        "q_xes3g5m_000003"
    )
    assert summary["content"]["missing_teaching_content"][0]["source_ref"].endswith(
        "mismatched.csv:row:4"
    )
    assert summary["rag"]["missing_rag_docs"][0]["canonical_question_id"] == (
        "q_xes3g5m_000005"
    )


def test_cli_writes_artifacts_and_prints_summary(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli-output"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.importing.build_xes3g5m_artifacts",
            "--source-rows",
            str(SOURCE_ROWS),
            "--kc-routes",
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


def test_cli_failure_prints_validation_summary(tmp_path: Path) -> None:
    output_dir = tmp_path / "cli-output"
    mismatched_source = tmp_path / "mismatched.csv"
    mismatched_source.write_text(
        SOURCE_ROWS.read_text(encoding="utf-8").replace(
            "3,2,异分母分数加法", "3,4,异分母分数加法", 1
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.importing.build_xes3g5m_artifacts",
            "--source-rows",
            str(mismatched_source),
            "--kc-routes",
            str(Q_MATRIX),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stderr)
    assert result.returncode == 2
    assert payload["status"] == "failed"
    assert payload["coverage_summary"]["validation"]["error_count"] == 1
    assert payload["coverage_summary"]["validation"]["gap_counts"] == {
        "kc_routes_mismatch": 1
    }
    assert payload["validation_errors"][0]["source_ref"].endswith("mismatched.csv:row:3")


def test_missing_file_and_malformed_row_fail_with_actionable_categories(
    tmp_path: Path,
) -> None:
    with pytest.raises(Assist2017BuildError) as missing_file:
        build_xes3g5m_import_artifacts(
            source_rows_path=tmp_path / "missing.csv",
            kc_routes_path=Q_MATRIX,
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
        build_xes3g5m_import_artifacts(
            source_rows_path=malformed,
            kc_routes_path=Q_MATRIX,
            generated_at="fixed",
        )
    assert malformed_row.value.issues[0].category == "malformed_row"
    assert malformed_row.value.issues[0].reason_code == "invalid_source_row"


def test_kc_routes_mismatch_fails_by_default_and_can_be_diagnosed(
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
        build_xes3g5m_import_artifacts(
            source_rows_path=mismatched_source,
            kc_routes_path=Q_MATRIX,
            generated_at="fixed",
        )
    assert mismatch.value.issues[0].category == "kc_routes_mismatch"
    assert mismatch.value.issues[0].reason_code == "concept_not_in_kc_routes_row"

    diagnostic = build_xes3g5m_import_artifacts(
        source_rows_path=mismatched_source,
        kc_routes_path=Q_MATRIX,
        generated_at="fixed",
        fail_on_errors=False,
    )
    assert diagnostic.coverage.summary["kc_routes"]["mismatch_count"] == 1
    assert any(gap.category == "kc_routes_mismatch" for gap in diagnostic.coverage.gaps)
