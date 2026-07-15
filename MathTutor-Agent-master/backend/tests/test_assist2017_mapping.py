from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.mapping.assist2017_mapping import (
    CanonicalMappingArtifact,
    CanonicalMappingRepository,
    build_mapping_artifact,
    coverage_diagnostics,
    load_mapping_artifact,
)
from backend.app.storage.content_repository import DemoTeachingContentRepository


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_Q_MATRIX = ROOT / "data" / "mapping" / "assist2017_q_matrix.fixture.csv"
FIXTURE_METADATA = ROOT / "data" / "mapping" / "assist2017_curated_metadata.fixture.json"
FIXTURE_ARTIFACT = ROOT / "data" / "mapping" / "assist2017_canonical_mapping.fixture.json"
TEACHING_CONTENT = ROOT / "data" / "content" / "demo_teaching_content.json"
RAG_DOCS = ROOT / "data" / "rag" / "demo_knowledge.json"


def test_canonical_mapping_schema_validates_required_fields() -> None:
    raw = json.loads(FIXTURE_ARTIFACT.read_text(encoding="utf-8"))
    artifact = CanonicalMappingArtifact.model_validate(raw)

    assert artifact.schema_version == "assist2017-canonical-mapping/v1"
    assert artifact.questions[0].assist2017_question_id == 1
    assert artifact.questions[0].concept_id == "c_multiplication_facts"
    assert artifact.questions[0].q_matrix_reference.concept_column_indices == [1]

    broken = dict(raw)
    broken["questions"] = [dict(raw["questions"][0])]
    broken["questions"][0].pop("q_matrix_reference")
    with pytest.raises(ValidationError):
        CanonicalMappingArtifact.model_validate(broken)


def test_build_mapping_artifact_from_fixture_inputs(tmp_path: Path) -> None:
    output_path = tmp_path / "mapping.json"

    artifact = build_mapping_artifact(
        q_matrix_path=FIXTURE_Q_MATRIX,
        metadata_path=FIXTURE_METADATA,
        teaching_content_path=TEACHING_CONTENT,
        rag_docs_path=RAG_DOCS,
        output_path=output_path,
        generated_at="test",
    )

    assert output_path.is_file()
    assert artifact.q_matrix.question_count == 6
    assert artifact.q_matrix.concept_count == 4
    assert artifact.questions[2].assist2017_question_id == 3
    assert artifact.questions[2].q_matrix_reference.concept_column_indices == [2]


def test_q_matrix_alignment_rejects_inconsistent_curated_metadata(tmp_path: Path) -> None:
    metadata = json.loads(FIXTURE_METADATA.read_text(encoding="utf-8"))
    metadata["questions"][0]["assist2017_concept_id"] = 2
    metadata_path = tmp_path / "bad_metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="Q-matrix row"):
        build_mapping_artifact(q_matrix_path=FIXTURE_Q_MATRIX, metadata_path=metadata_path)


def test_coverage_diagnostics_reports_counts_and_missing_items() -> None:
    artifact = load_mapping_artifact(FIXTURE_ARTIFACT)
    teaching_content = json.loads(TEACHING_CONTENT.read_text(encoding="utf-8"))
    rag_docs = json.loads(RAG_DOCS.read_text(encoding="utf-8"))

    report = coverage_diagnostics(
        artifact,
        q_matrix_path=FIXTURE_Q_MATRIX,
        teaching_content=teaching_content,
        rag_docs=rag_docs,
    ).to_report()

    assert report["mapped_question_count"] == 5
    assert report["mapped_concept_count"] == 3
    assert report["missing_questions"] == [6]
    assert report["missing_concepts"] == [4]
    assert report["missing_teaching_content"] == ["q_fixture_missing_content"]
    assert report["missing_rag_docs"] == ["rag_missing_fixture_doc"]


def test_repository_queries_by_question_and_concept() -> None:
    repository = CanonicalMappingRepository.from_path(FIXTURE_ARTIFACT)

    question = repository.get_by_mathtutor_question_id("q_frac_001")
    assert question is not None
    assert question.assist2017_question_id == 3
    assert question.assist2017_concept_id == 2

    concept = repository.concept_for_assist2017_concept_id(2)
    assert concept is not None
    assert concept.concept_id == "c_fraction_addition"


def test_content_repository_uses_mapping_without_breaking_mock_mode() -> None:
    questions = DemoTeachingContentRepository().list_questions()

    assert questions
    first_question = questions[0]
    assert first_question["question_id"] == "q_mem_001"
    assert first_question["assist2017_question_id"] == 1
    assert first_question["assist2017_concept_id"] == 1
    assert first_question["teaching_type"] == "memory"
    assert first_question["q_matrix_reference"]["concept_column_indices"] == [1]

    unmapped_question = next(question for question in questions if question["question_id"] == "q_mem_003")
    assert unmapped_question["assist2017_question_id"] == 3
    assert "assist2017_concept_id" not in unmapped_question
