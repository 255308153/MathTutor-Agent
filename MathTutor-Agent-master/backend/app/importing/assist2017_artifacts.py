from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..mapping.assist2017_mapping import (
    CanonicalConceptMapping,
    CanonicalMappingArtifact,
    CanonicalQuestionMapping,
    MappingProvenance,
    PROJECT_ROOT,
    QMatrixArtifactSummary,
    read_q_matrix,
)
from ..rag.schema import RAGDocument


BUILD_SCHEMA_VERSION = "assist2017-import-build/v1"
CONTENT_SCHEMA_VERSION = "assist2017-content-import/v1"
RAG_SCHEMA_VERSION = "assist2017-rag-documents/v1"
COVERAGE_SCHEMA_VERSION = "assist2017-coverage-report/v1"
SMOKE_SCHEMA_VERSION = "assist2017-smoke-dataset/v1"

ValidationCategory = Literal[
    "missing_file",
    "malformed_row",
    "q_matrix_mismatch",
    "missing_question_mapping",
    "missing_concept_mapping",
    "missing_teaching_content",
    "missing_rag_doc",
]


class Assist2017BuildError(RuntimeError):
    def __init__(
        self,
        issues: list["ValidationIssue"],
        coverage_summary: dict[str, Any] | None = None,
    ) -> None:
        self.issues = issues
        self.coverage_summary = coverage_summary or {
            "validation": _validation_summary(issues)
        }
        messages = "; ".join(issue.message for issue in issues)
        super().__init__(messages)


class ValidationIssue(BaseModel):
    category: ValidationCategory
    reason_code: str = Field(min_length=1)
    severity: Literal["error", "warning", "info"] = "warning"
    message: str = Field(min_length=1)
    source_ref: str | None = None
    assist2017_question_id: int | None = Field(default=None, ge=1)
    assist2017_concept_id: int | None = Field(default=None, ge=1)
    canonical_question_id: str | None = None
    canonical_concept_id: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class ArtifactBuildMetadata(BaseModel):
    schema_version: Literal["assist2017-import-build/v1"] = BUILD_SCHEMA_VERSION
    dataset: Literal["assist2017"] = "assist2017"
    generated_at: str
    source_paths: dict[str, str]
    row_counts: dict[str, int] = Field(default_factory=dict)
    coverage_summary: dict[str, Any] = Field(default_factory=dict)
    validation_errors: list[ValidationIssue] = Field(default_factory=list)


class ImportedConcept(BaseModel):
    assist2017_concept_id: int = Field(ge=1)
    concept_id: str = Field(min_length=1)
    concept_name: str = Field(min_length=1)
    teaching_type: str = Field(min_length=1)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ContentAvailability(BaseModel):
    status: Literal["available", "partial", "missing"] = "available"
    has_stem: bool = True
    has_answer: bool = True
    has_explanation: bool = True
    has_concept_metadata: bool = True
    missing_fields: list[str] = Field(default_factory=list)
    missing_reason_codes: list[str] = Field(default_factory=list)
    fallback_message: str | None = None


class ImportedQuestion(BaseModel):
    question_id: str = Field(min_length=1)
    assist2017_question_id: int = Field(ge=1)
    stem: str | None = None
    standard_answer: str | None = None
    explanation: str | None = None
    concept_id: str = Field(min_length=1)
    concept_ids: list[str] = Field(min_length=1)
    concept_name: str = Field(min_length=1)
    assist2017_concept_id: int = Field(ge=1)
    difficulty: float = Field(ge=0.0, le=1.0)
    teaching_type: str = Field(min_length=1)
    mistake_patterns: list[str] = Field(default_factory=list)
    rag_doc_ids: list[str] = Field(default_factory=list)
    q_matrix_reference: dict[str, Any] = Field(default_factory=dict)
    canonical_mapping: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    content_availability: ContentAvailability


class ContentImportArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["assist2017-content-import/v1"] = CONTENT_SCHEMA_VERSION
    dataset: Literal["assist2017"] = "assist2017"
    metadata: ArtifactBuildMetadata
    concept_teaching_type_map: dict[str, str]
    concepts: list[ImportedConcept]
    questions: list[ImportedQuestion]


class RAGDocumentArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["assist2017-rag-documents/v1"] = RAG_SCHEMA_VERSION
    dataset: Literal["assist2017"] = "assist2017"
    metadata: ArtifactBuildMetadata
    documents: list[RAGDocument]


class CoverageGap(BaseModel):
    category: ValidationCategory
    reason_code: str = Field(min_length=1)
    severity: Literal["error", "warning", "info"] = "warning"
    source_ref: str | None = None
    canonical_question_id: str | None = None
    canonical_concept_id: str | None = None
    assist2017_question_id: int | None = Field(default=None, ge=1)
    assist2017_concept_id: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=1)
    provenance: dict[str, Any] = Field(default_factory=dict)


class CoverageReportArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["assist2017-coverage-report/v1"] = COVERAGE_SCHEMA_VERSION
    dataset: Literal["assist2017"] = "assist2017"
    metadata: ArtifactBuildMetadata
    summary: dict[str, Any]
    gaps: list[CoverageGap] = Field(default_factory=list)


class SmokeLearningStep(BaseModel):
    event_type: Literal["chat_message", "answer_submitted"]
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)


class SmokeLearningPath(BaseModel):
    path_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    canonical_question_id: str = Field(min_length=1)
    canonical_concept_id: str = Field(min_length=1)
    assist2017_question_id: int = Field(ge=1)
    assist2017_concept_id: int = Field(ge=1)
    steps: list[SmokeLearningStep] = Field(min_length=1)


class SmokeDatasetArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["assist2017-smoke-dataset/v1"] = SMOKE_SCHEMA_VERSION
    dataset: Literal["assist2017"] = "assist2017"
    metadata: ArtifactBuildMetadata
    learning_paths: list[SmokeLearningPath]


class Assist2017ImportArtifacts(BaseModel):
    mapping: CanonicalMappingArtifact
    content: ContentImportArtifact
    rag: RAGDocumentArtifact
    coverage: CoverageReportArtifact
    smoke: SmokeDatasetArtifact


@dataclass(frozen=True)
class SourceRow:
    row_number: int
    assist2017_question_id: int
    assist2017_concept_id: int
    concept_name: str
    teaching_type: str
    stem: str | None
    standard_answer: str | None
    explanation: str | None
    difficulty: float
    mistake_patterns: list[str]
    source_row_id: str

    @property
    def question_id(self) -> str:
        return canonical_question_id(self.assist2017_question_id)

    @property
    def concept_id(self) -> str:
        return canonical_concept_id(self.assist2017_concept_id)


def build_assist2017_import_artifacts(
    *,
    source_rows_path: str | Path,
    q_matrix_path: str | Path,
    output_dir: str | Path | None = None,
    generated_at: str | None = None,
    fail_on_errors: bool = True,
) -> Assist2017ImportArtifacts:
    generated = generated_at or datetime.now(UTC).isoformat()
    source_paths = {
        "source_rows": _display_path(source_rows_path),
        "q_matrix": _display_path(q_matrix_path),
    }
    issues: list[ValidationIssue] = []

    rows = _read_source_rows(source_rows_path, issues)
    q_rows = _read_q_matrix(q_matrix_path, issues)
    if any(issue.severity == "error" for issue in issues):
        _raise_if_needed(issues, fail_on_errors)
        q_rows = q_rows or []

    rows_by_question_id: dict[int, SourceRow] = {}
    for row in rows:
        if row.assist2017_question_id in rows_by_question_id:
            issues.append(
                _issue(
                    category="malformed_row",
                    reason_code="duplicate_question_id",
                    severity="error",
                    message=f"Duplicate assist2017_question_id {row.assist2017_question_id}.",
                    source_ref=f"{source_paths['source_rows']}:row:{row.row_number}",
                    row=row,
                )
            )
            continue
        rows_by_question_id[row.assist2017_question_id] = row

    aligned_rows: list[SourceRow] = []
    for row in sorted(rows_by_question_id.values(), key=lambda item: item.assist2017_question_id):
        q_matrix_concepts = (
            q_rows[row.assist2017_question_id - 1]
            if 1 <= row.assist2017_question_id <= len(q_rows)
            else []
        )
        if row.assist2017_question_id < 1 or row.assist2017_question_id > len(q_rows):
            issues.append(
                _issue(
                    category="q_matrix_mismatch",
                    reason_code="question_outside_q_matrix",
                    severity="error",
                    message=(
                        f"Question {row.assist2017_question_id} is outside Q-matrix "
                        f"row range 1..{len(q_rows)}."
                    ),
                    source_ref=f"{source_paths['source_rows']}:row:{row.row_number}",
                    row=row,
                    provenance={
                        "q_matrix_path": source_paths["q_matrix"],
                        "q_matrix_question_count": len(q_rows),
                    },
                )
            )
            continue
        if row.assist2017_concept_id not in q_matrix_concepts:
            issues.append(
                _issue(
                    category="q_matrix_mismatch",
                    reason_code="concept_not_in_q_matrix_row",
                    severity="error",
                    message=(
                        f"Question {row.assist2017_question_id} declares concept "
                        f"{row.assist2017_concept_id}, but Q-matrix row has "
                        f"{q_matrix_concepts}."
                    ),
                    source_ref=f"{source_paths['source_rows']}:row:{row.row_number}",
                    row=row,
                    provenance={
                        "declared_assist2017_concept_id": row.assist2017_concept_id,
                        "q_matrix_concept_ids": q_matrix_concepts,
                        "q_matrix_path": source_paths["q_matrix"],
                        "q_matrix_row": row.assist2017_question_id,
                    },
                )
            )
            continue
        aligned_rows.append(row)

    _raise_if_needed(issues, fail_on_errors)

    q_matrix_question_ids = set(range(1, len(q_rows) + 1))
    q_matrix_concept_ids = {concept_id for q_row in q_rows for concept_id in q_row}
    mapped_question_ids = {row.assist2017_question_id for row in aligned_rows}
    mapped_concept_ids = {row.assist2017_concept_id for row in aligned_rows}

    for question_id in sorted(q_matrix_question_ids - mapped_question_ids):
        issues.append(
            ValidationIssue(
                category="missing_question_mapping",
                reason_code="q_matrix_row_without_source_question",
                severity="warning",
                message=f"Q-matrix row {question_id} has no imported source question.",
                source_ref=f"{source_paths['q_matrix']}:row:{question_id}",
                assist2017_question_id=question_id,
                canonical_question_id=canonical_question_id(question_id),
                provenance={
                    "q_matrix_path": source_paths["q_matrix"],
                    "q_matrix_row": question_id,
                },
            )
        )
    for concept_id in sorted(q_matrix_concept_ids - mapped_concept_ids):
        issues.append(
            ValidationIssue(
                category="missing_concept_mapping",
                reason_code="q_matrix_concept_without_source_concept",
                severity="warning",
                message=f"Q-matrix concept column {concept_id} has no imported concept metadata.",
                source_ref=f"{source_paths['q_matrix']}:column:{concept_id}",
                assist2017_concept_id=concept_id,
                canonical_concept_id=canonical_concept_id(concept_id),
                provenance={
                    "q_matrix_path": source_paths["q_matrix"],
                    "q_matrix_concept_column": concept_id,
                },
            )
        )

    mapping, content = _build_mapping_and_content(
        rows=aligned_rows,
        q_rows=q_rows,
        q_matrix_path=q_matrix_path,
        generated_at=generated,
        source_paths=source_paths,
        issues=issues,
    )
    rag_documents = _build_rag_documents(rows=aligned_rows, source_paths=source_paths)
    expected_rag_doc_ids = {doc_id for question in content.questions for doc_id in question.rag_doc_ids}
    actual_rag_doc_ids = {document.doc_id for document in rag_documents}
    for missing_doc_id in sorted(expected_rag_doc_ids - actual_rag_doc_ids):
        row = _row_for_doc_id(aligned_rows, missing_doc_id)
        issues.append(
            _issue(
                category="missing_rag_doc",
                reason_code="expected_rag_doc_not_generated",
                severity="warning",
                message=f"Expected RAG document {missing_doc_id} was not generated.",
                source_ref=(
                    f"{source_paths['source_rows']}:row:{row.row_number}" if row else None
                ),
                row=row,
                provenance={"doc_id": missing_doc_id},
            )
        )

    summary = _coverage_summary(
        q_rows=q_rows,
        rows=aligned_rows,
        rag_documents=rag_documents,
        issues=issues,
    )
    metadata = _metadata(
        generated_at=generated,
        source_paths=source_paths,
        row_counts={
            "source_rows": len(rows),
            "valid_source_rows": len(aligned_rows),
            "q_matrix_questions": len(q_rows),
            "q_matrix_concepts": len(q_matrix_concept_ids),
            "content_questions": len(content.questions),
            "rag_documents": len(rag_documents),
        },
        coverage_summary=_compact_coverage_summary(summary),
        validation_errors=issues,
    )
    content = content.model_copy(update={"metadata": metadata})
    rag = RAGDocumentArtifact(metadata=metadata, documents=rag_documents)
    coverage = CoverageReportArtifact(
        metadata=metadata.model_copy(update={"coverage_summary": summary}),
        summary=summary,
        gaps=[
            CoverageGap.model_validate(issue.model_dump())
            for issue in issues
            if issue.category
            in {
                "missing_question_mapping",
                "missing_concept_mapping",
                "q_matrix_mismatch",
                "missing_teaching_content",
                "missing_rag_doc",
            }
        ],
    )
    smoke = _build_smoke_artifact(
        rows=aligned_rows,
        metadata=metadata,
    )
    artifacts = Assist2017ImportArtifacts(
        mapping=mapping,
        content=content,
        rag=rag,
        coverage=coverage,
        smoke=smoke,
    )

    if output_dir is not None:
        write_assist2017_import_artifacts(artifacts, output_dir)
    return artifacts


def write_assist2017_import_artifacts(
    artifacts: Assist2017ImportArtifacts,
    output_dir: str | Path,
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    outputs = {
        "mapping": directory / "canonical_mapping.json",
        "content": directory / "content_import.json",
        "rag": directory / "rag_documents.json",
        "coverage": directory / "coverage_report.json",
        "smoke": directory / "smoke_dataset.json",
    }
    outputs["mapping"].write_text(
        _to_json(artifacts.mapping.model_dump()),
        encoding="utf-8",
    )
    outputs["content"].write_text(_to_json(artifacts.content.model_dump()), encoding="utf-8")
    outputs["rag"].write_text(_to_json(artifacts.rag.model_dump()), encoding="utf-8")
    outputs["coverage"].write_text(_to_json(artifacts.coverage.model_dump()), encoding="utf-8")
    outputs["smoke"].write_text(_to_json(artifacts.smoke.model_dump()), encoding="utf-8")
    return outputs


def canonical_question_id(assist2017_question_id: int) -> str:
    return f"q_assist2017_{assist2017_question_id:06d}"


def canonical_concept_id(assist2017_concept_id: int) -> str:
    return f"c_assist2017_{assist2017_concept_id:04d}"


def _build_mapping_and_content(
    *,
    rows: list[SourceRow],
    q_rows: list[list[int]],
    q_matrix_path: str | Path,
    generated_at: str,
    source_paths: dict[str, str],
    issues: list[ValidationIssue],
) -> tuple[CanonicalMappingArtifact, ContentImportArtifact]:
    concepts_by_id: dict[int, SourceRow] = {}
    for row in rows:
        concepts_by_id.setdefault(row.assist2017_concept_id, row)

    concepts = [
        CanonicalConceptMapping(
            assist2017_concept_id=concept_id,
            concept_id=row.concept_id,
            concept_name=row.concept_name,
            teaching_type=row.teaching_type,
            source_provenance=MappingProvenance(
                source=Path(source_paths["source_rows"]).name,
                confidence="derived",
                notes=f"source_row_id={row.source_row_id}",
            ),
        )
        for concept_id, row in sorted(concepts_by_id.items())
    ]

    questions: list[CanonicalQuestionMapping] = []
    imported_questions: list[ImportedQuestion] = []
    for row in rows:
        q_matrix_reference = {
            "q_matrix_path": _display_path(q_matrix_path),
            "row_index": row.assist2017_question_id,
            "concept_column_indices": q_rows[row.assist2017_question_id - 1],
        }
        expected_rag_doc_ids = _expected_rag_doc_ids(row)
        questions.append(
            CanonicalQuestionMapping(
                assist2017_question_id=row.assist2017_question_id,
                question_id=row.question_id,
                concept_id=row.concept_id,
                concept_name=row.concept_name,
                teaching_type=row.teaching_type,
                q_matrix_reference=q_matrix_reference,
                source_provenance=MappingProvenance(
                    source=Path(source_paths["source_rows"]).name,
                    confidence="derived",
                    notes=f"source_row_id={row.source_row_id}",
                ),
                assist2017_concept_id=row.assist2017_concept_id,
                rag_doc_ids=expected_rag_doc_ids,
            )
        )

        availability = _content_availability(row)
        if availability.status != "available":
            issues.append(
                _issue(
                    category="missing_teaching_content",
                    reason_code="essential_teaching_field_missing",
                    severity="warning",
                    message=availability.fallback_message
                    or f"{row.question_id} has incomplete teaching content.",
                    source_ref=f"{source_paths['source_rows']}:row:{row.row_number}",
                    row=row,
                    provenance={
                        "missing_fields": availability.missing_fields,
                        "missing_reason_codes": availability.missing_reason_codes,
                        "content_availability": availability.model_dump(),
                    },
                )
            )
        imported_questions.append(
            ImportedQuestion(
                question_id=row.question_id,
                assist2017_question_id=row.assist2017_question_id,
                stem=row.stem,
                standard_answer=row.standard_answer,
                explanation=row.explanation,
                concept_id=row.concept_id,
                concept_ids=[row.concept_id],
                concept_name=row.concept_name,
                assist2017_concept_id=row.assist2017_concept_id,
                difficulty=row.difficulty,
                teaching_type=row.teaching_type,
                mistake_patterns=row.mistake_patterns,
                rag_doc_ids=expected_rag_doc_ids,
                q_matrix_reference=q_matrix_reference,
                canonical_mapping={
                    "question_id": row.question_id,
                    "concept_id": row.concept_id,
                    "concept_name": row.concept_name,
                    "teaching_type": row.teaching_type,
                    "assist2017_question_id": row.assist2017_question_id,
                    "assist2017_concept_id": row.assist2017_concept_id,
                    "q_matrix_reference": q_matrix_reference,
                    "source": Path(source_paths["source_rows"]).name,
                },
                provenance={
                    "content_source": source_paths["source_rows"],
                    "source_row_id": row.source_row_id,
                    "assist2017_question_id": row.assist2017_question_id,
                    "assist2017_concept_id": row.assist2017_concept_id,
                    "q_matrix_reference": q_matrix_reference,
                    "answer_source": (
                        source_paths["source_rows"] if row.standard_answer is not None else None
                    ),
                    "explanation_source": (
                        source_paths["source_rows"] if row.explanation is not None else None
                    ),
                },
                content_availability=availability,
            )
        )

    mapping = CanonicalMappingArtifact(
        generated_at=generated_at,
        q_matrix=QMatrixArtifactSummary(
            source_path=_display_path(q_matrix_path),
            question_count=len(q_rows),
            concept_count=max((max(row) for row in q_rows if row), default=0),
        ),
        concepts=concepts,
        questions=questions,
    )
    content = ContentImportArtifact(
        metadata=_metadata(generated_at=generated_at, source_paths=source_paths),
        concept_teaching_type_map={
            concept.concept_id: concept.teaching_type for concept in concepts
        },
        concepts=[
            ImportedConcept(
                assist2017_concept_id=concept.assist2017_concept_id,
                concept_id=concept.concept_id,
                concept_name=concept.concept_name,
                teaching_type=concept.teaching_type,
                provenance={
                    "mapping_source": concept.source_provenance.source,
                    "source_row_id": concepts_by_id[
                        concept.assist2017_concept_id
                    ].source_row_id,
                },
            )
            for concept in concepts
        ],
        questions=imported_questions,
    )
    return mapping, content


def _build_rag_documents(
    *,
    rows: list[SourceRow],
    source_paths: dict[str, str],
) -> list[RAGDocument]:
    documents: list[RAGDocument] = []
    rows_by_concept: dict[int, SourceRow] = {}
    for row in rows:
        rows_by_concept.setdefault(row.assist2017_concept_id, row)

    for row in sorted(rows_by_concept.values(), key=lambda item: item.assist2017_concept_id):
        documents.append(
            _rag_document(
                doc_id=_doc_id(row, "concept_note"),
                doc_type="concept_note",
                title=f"{row.concept_name}：核心概念",
                content=f"{row.concept_name} 是 ASSISTments2017 导入知识点，可用同概念题目做针对练习。",
                row=row,
                source_paths=source_paths,
                question_aligned=False,
            )
        )
        documents.append(
            _rag_document(
                doc_id=_doc_id(row, "learning_strategy"),
                doc_type="learning_strategy",
                title=f"{row.concept_name}：学习策略",
                content="先定位薄弱知识点，再选择内容完整、难度接近当前掌握度的题目练习。",
                row=row,
                source_paths=source_paths,
                question_aligned=False,
            )
        )

    for row in rows:
        if row.explanation is not None:
            documents.append(
                _rag_document(
                    doc_id=_doc_id(row, "question_explanation"),
                    doc_type="question_explanation",
                    title=f"{row.question_id} 题解",
                    content=row.explanation,
                    row=row,
                    source_paths=source_paths,
                    question_aligned=True,
                )
            )
        if row.mistake_patterns:
            documents.append(
                _rag_document(
                    doc_id=_doc_id(row, "mistake_pattern"),
                    doc_type="mistake_pattern",
                    title=f"{row.question_id} 常见错因",
                    content="；".join(row.mistake_patterns),
                    row=row,
                    source_paths=source_paths,
                    question_aligned=True,
                )
            )
    return sorted(documents, key=lambda document: document.doc_id)


def _rag_document(
    *,
    doc_id: str,
    doc_type: str,
    title: str,
    content: str,
    row: SourceRow,
    source_paths: dict[str, str],
    question_aligned: bool,
) -> RAGDocument:
    question_id = row.question_id if question_aligned else None
    return RAGDocument(
        doc_id=doc_id,
        doc_type=doc_type,  # type: ignore[arg-type]
        title=title,
        content=content,
        source=f"{source_paths['source_rows']}#row-{row.row_number}",
        concept_id=row.concept_id,
        question_id=question_id,
        assist2017_question_id=row.assist2017_question_id if question_aligned else None,
        assist2017_concept_id=row.assist2017_concept_id,
        canonical_mapping={
            "question_id": question_id,
            "concept_id": row.concept_id,
            "concept_name": row.concept_name,
            "teaching_type": row.teaching_type,
            "assist2017_question_id": (
                row.assist2017_question_id if question_aligned else None
            ),
            "assist2017_concept_id": row.assist2017_concept_id,
            "source": Path(source_paths["source_rows"]).name,
        },
        provenance={
            "rag_source": "assist2017_import_builder",
            "source_row_id": row.source_row_id,
            "content_source": source_paths["source_rows"],
        },
        coverage={
            "coverage_type": "question" if question_aligned else "concept",
            "doc_type": doc_type,
            "question_aligned": question_aligned,
            "concept_aligned": True,
            "missing_reason": None,
        },
        keywords=[row.concept_name, row.question_id, doc_type],
    )


def _build_smoke_artifact(
    *,
    rows: list[SourceRow],
    metadata: ArtifactBuildMetadata,
) -> SmokeDatasetArtifact:
    complete_rows = [
        row
        for row in rows
        if row.stem is not None and row.standard_answer is not None and row.explanation is not None
    ]
    if not complete_rows:
        return SmokeDatasetArtifact(metadata=metadata, learning_paths=[])
    row = complete_rows[0]
    return SmokeDatasetArtifact(
        metadata=metadata,
        learning_paths=[
            SmokeLearningPath(
                path_id=f"smoke_{row.question_id}",
                description="推荐到答题到 TeachingTrace 的 ASSISTments2017 fixture smoke。",
                canonical_question_id=row.question_id,
                canonical_concept_id=row.concept_id,
                assist2017_question_id=row.assist2017_question_id,
                assist2017_concept_id=row.assist2017_concept_id,
                steps=[
                    SmokeLearningStep(
                        event_type="chat_message",
                        message="我下一步应该练什么？",
                        payload={"preferred_concept_id": row.concept_id},
                        expected={
                            "recommended_question_id": row.question_id,
                            "canonical_concept_id": row.concept_id,
                        },
                    ),
                    SmokeLearningStep(
                        event_type="answer_submitted",
                        message="提交一条 fixture 答案",
                        payload={
                            "question_id": row.question_id,
                            "answer": "__wrong_fixture_answer__",
                        },
                        expected={
                            "is_correct": False,
                            "canonical_concept_id": row.concept_id,
                            "kt_facts_authoritative": True,
                        },
                    ),
                ],
            )
        ],
    )


def _coverage_summary(
    *,
    q_rows: list[list[int]],
    rows: list[SourceRow],
    rag_documents: list[RAGDocument],
    issues: list[ValidationIssue],
) -> dict[str, Any]:
    q_matrix_question_ids = set(range(1, len(q_rows) + 1))
    q_matrix_concept_ids = {concept_id for row in q_rows for concept_id in row}
    mapped_question_ids = {row.assist2017_question_id for row in rows}
    mapped_concept_ids = {row.assist2017_concept_id for row in rows}
    complete_content = [
        row
        for row in rows
        if row.stem is not None and row.standard_answer is not None and row.explanation is not None
    ]
    validation_summary = _validation_summary(issues)
    gap_counts = validation_summary["gap_counts"]
    doc_type_counts: dict[str, int] = {}
    for document in rag_documents:
        doc_type_counts[document.doc_type] = doc_type_counts.get(document.doc_type, 0) + 1
    content_gaps = [
        _gap_summary(issue)
        for issue in issues
        if issue.category == "missing_teaching_content"
    ]
    rag_gaps = [
        _gap_summary(issue)
        for issue in issues
        if issue.category == "missing_rag_doc"
    ]
    q_matrix_gaps = [
        _gap_summary(issue)
        for issue in issues
        if issue.category == "q_matrix_mismatch"
    ]
    return {
        "mapping": {
            "mapped_question_count": len(mapped_question_ids),
            "unmapped_question_count": len(q_matrix_question_ids - mapped_question_ids),
            "mapped_concept_count": len(mapped_concept_ids),
            "unmapped_concept_count": len(q_matrix_concept_ids - mapped_concept_ids),
            "mapped_question_ids": [
                canonical_question_id(question_id)
                for question_id in sorted(mapped_question_ids)
            ],
            "unmapped_question_ids": [
                canonical_question_id(question_id)
                for question_id in sorted(q_matrix_question_ids - mapped_question_ids)
            ],
            "mapped_concept_ids": [
                canonical_concept_id(concept_id)
                for concept_id in sorted(mapped_concept_ids)
            ],
            "unmapped_concept_ids": [
                canonical_concept_id(concept_id)
                for concept_id in sorted(q_matrix_concept_ids - mapped_concept_ids)
            ],
            "missing_question_mappings": [
                _gap_summary(issue)
                for issue in issues
                if issue.category == "missing_question_mapping"
            ],
            "missing_concept_mappings": [
                _gap_summary(issue)
                for issue in issues
                if issue.category == "missing_concept_mapping"
            ],
        },
        "content": {
            "question_count": len(rows),
            "complete_question_count": len(complete_content),
            "partial_question_count": len(rows) - len(complete_content),
            "missing_teaching_content_count": gap_counts.get("missing_teaching_content", 0),
            "missing_teaching_content": content_gaps,
        },
        "rag": {
            "document_count": len(rag_documents),
            "missing_rag_doc_count": gap_counts.get("missing_rag_doc", 0),
            "doc_type_counts": doc_type_counts,
            "missing_rag_docs": rag_gaps,
        },
        "q_matrix": {
            "question_count": len(q_rows),
            "concept_count": len(q_matrix_concept_ids),
            "mismatch_count": gap_counts.get("q_matrix_mismatch", 0),
            "mismatches": q_matrix_gaps,
        },
        "validation": validation_summary,
    }


def _validation_summary(issues: list[ValidationIssue]) -> dict[str, Any]:
    gap_counts: dict[str, int] = {}
    for issue in issues:
        gap_counts[issue.category] = gap_counts.get(issue.category, 0) + 1
    return {
        "error_count": sum(1 for issue in issues if issue.severity == "error"),
        "warning_count": sum(1 for issue in issues if issue.severity == "warning"),
        "gap_counts": gap_counts,
    }


def _compact_coverage_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "mapping": {
            "mapped_question_count": summary["mapping"]["mapped_question_count"],
            "unmapped_question_count": summary["mapping"]["unmapped_question_count"],
            "mapped_concept_count": summary["mapping"]["mapped_concept_count"],
            "unmapped_concept_count": summary["mapping"]["unmapped_concept_count"],
        },
        "content": {
            "question_count": summary["content"]["question_count"],
            "complete_question_count": summary["content"]["complete_question_count"],
            "partial_question_count": summary["content"]["partial_question_count"],
            "missing_teaching_content_count": summary["content"][
                "missing_teaching_content_count"
            ],
        },
        "rag": {
            "document_count": summary["rag"]["document_count"],
            "missing_rag_doc_count": summary["rag"]["missing_rag_doc_count"],
            "doc_type_counts": summary["rag"]["doc_type_counts"],
        },
        "q_matrix": {
            "question_count": summary["q_matrix"]["question_count"],
            "concept_count": summary["q_matrix"]["concept_count"],
            "mismatch_count": summary["q_matrix"]["mismatch_count"],
        },
        "validation": summary["validation"],
    }


def _gap_summary(issue: ValidationIssue) -> dict[str, Any]:
    payload = {
        "category": issue.category,
        "reason_code": issue.reason_code,
        "severity": issue.severity,
        "source_ref": issue.source_ref,
        "canonical_question_id": issue.canonical_question_id,
        "canonical_concept_id": issue.canonical_concept_id,
        "assist2017_question_id": issue.assist2017_question_id,
        "assist2017_concept_id": issue.assist2017_concept_id,
        "message": issue.message,
        "provenance": issue.provenance,
    }
    if issue.provenance.get("doc_id"):
        payload["doc_id"] = issue.provenance["doc_id"]
    if issue.provenance.get("missing_fields"):
        payload["missing_fields"] = issue.provenance["missing_fields"]
    if issue.provenance.get("missing_reason_codes"):
        payload["missing_reason_codes"] = issue.provenance["missing_reason_codes"]
    return payload


def _read_source_rows(path: str | Path, issues: list[ValidationIssue]) -> list[SourceRow]:
    resolved = _resolve_project_path(path)
    if not resolved.is_file():
        issues.append(
            ValidationIssue(
                category="missing_file",
                reason_code="source_rows_not_found",
                severity="error",
                message=f"ASSIST2017 source rows file not found: {_display_path(path)}.",
                source_ref=_display_path(path),
            )
        )
        return []

    required = {
        "assist2017_question_id",
        "assist2017_concept_id",
        "concept_name",
        "teaching_type",
        "question_text",
        "correct_answer",
        "explanation",
        "difficulty",
        "mistake_patterns",
        "source_row_id",
    }
    rows: list[SourceRow] = []
    with resolved.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = set(reader.fieldnames or [])
        missing_headers = sorted(required - headers)
        if missing_headers:
            issues.append(
                ValidationIssue(
                    category="malformed_row",
                    reason_code="missing_required_columns",
                    severity="error",
                    message=f"Source rows CSV missing columns: {', '.join(missing_headers)}.",
                    source_ref=_display_path(path),
                )
            )
            return []
        for row_number, raw in enumerate(reader, start=2):
            try:
                rows.append(_parse_source_row(raw, row_number=row_number))
            except (ValueError, KeyError, ValidationError) as exc:
                issues.append(
                    ValidationIssue(
                        category="malformed_row",
                        reason_code="invalid_source_row",
                        severity="error",
                        message=f"Malformed source row {row_number}: {exc}.",
                        source_ref=f"{_display_path(path)}:row:{row_number}",
                    )
                )
    return rows


def _parse_source_row(raw: dict[str, str], *, row_number: int) -> SourceRow:
    assist_question_id = int(_required(raw, "assist2017_question_id"))
    assist_concept_id = int(_required(raw, "assist2017_concept_id"))
    difficulty = float(_required(raw, "difficulty"))
    if not 0.0 <= difficulty <= 1.0:
        raise ValueError("difficulty must be between 0.0 and 1.0")
    concept_name = _required(raw, "concept_name")
    teaching_type = _required(raw, "teaching_type")
    source_row_id = _required(raw, "source_row_id")
    return SourceRow(
        row_number=row_number,
        assist2017_question_id=assist_question_id,
        assist2017_concept_id=assist_concept_id,
        concept_name=concept_name,
        teaching_type=teaching_type,
        stem=_blank_to_none(raw.get("question_text")),
        standard_answer=_blank_to_none(raw.get("correct_answer")),
        explanation=_blank_to_none(raw.get("explanation")),
        difficulty=difficulty,
        mistake_patterns=_split_pipe_list(raw.get("mistake_patterns")),
        source_row_id=source_row_id,
    )


def _read_q_matrix(path: str | Path, issues: list[ValidationIssue]) -> list[list[int]]:
    resolved = _resolve_project_path(path)
    if not resolved.is_file():
        issues.append(
            ValidationIssue(
                category="missing_file",
                reason_code="q_matrix_not_found",
                severity="error",
                message=f"ASSIST2017 Q-matrix file not found: {_display_path(path)}.",
                source_ref=_display_path(path),
            )
        )
        return []
    try:
        return read_q_matrix(resolved)
    except ValueError as exc:
        issues.append(
            ValidationIssue(
                category="malformed_row",
                reason_code="invalid_q_matrix",
                severity="error",
                message=f"Malformed Q-matrix: {exc}.",
                source_ref=_display_path(path),
            )
        )
        return []


def _content_availability(row: SourceRow) -> ContentAvailability:
    missing_fields: list[str] = []
    if row.stem is None:
        missing_fields.append("stem")
    if row.standard_answer is None:
        missing_fields.append("standard_answer")
    if row.explanation is None:
        missing_fields.append("explanation")
    status = "available" if not missing_fields else "partial"
    labels = {
        "stem": "题干",
        "standard_answer": "标准答案",
        "explanation": "解析",
    }
    return ContentAvailability(
        status=status,
        has_stem="stem" not in missing_fields,
        has_answer="standard_answer" not in missing_fields,
        has_explanation="explanation" not in missing_fields,
        has_concept_metadata=True,
        missing_fields=missing_fields,
        missing_reason_codes=[f"missing_{field}" for field in missing_fields],
        fallback_message=(
            None
            if not missing_fields
            else f"{row.question_id} 缺少{'、'.join(labels[field] for field in missing_fields)}，请补齐 ASSISTments2017 教学内容。"
        ),
    )


def _expected_rag_doc_ids(row: SourceRow) -> list[str]:
    return [
        _doc_id(row, "concept_note"),
        _doc_id(row, "question_explanation"),
        _doc_id(row, "mistake_pattern"),
        _doc_id(row, "learning_strategy"),
    ]


def _doc_id(row: SourceRow, doc_type: str) -> str:
    if doc_type in {"concept_note", "learning_strategy"}:
        return f"rag_assist2017_c{row.assist2017_concept_id:04d}_{doc_type}"
    return f"rag_assist2017_q{row.assist2017_question_id:06d}_{doc_type}"


def _row_for_doc_id(rows: list[SourceRow], doc_id: str) -> SourceRow | None:
    for row in rows:
        if doc_id in set(_expected_rag_doc_ids(row)):
            return row
    return None


def _metadata(
    *,
    generated_at: str,
    source_paths: dict[str, str],
    row_counts: dict[str, int] | None = None,
    coverage_summary: dict[str, Any] | None = None,
    validation_errors: list[ValidationIssue] | None = None,
) -> ArtifactBuildMetadata:
    return ArtifactBuildMetadata(
        generated_at=generated_at,
        source_paths=source_paths,
        row_counts=row_counts or {},
        coverage_summary=coverage_summary or {},
        validation_errors=validation_errors or [],
    )


def _issue(
    *,
    category: ValidationCategory,
    reason_code: str,
    severity: Literal["error", "warning", "info"],
    message: str,
    source_ref: str | None = None,
    row: SourceRow | None = None,
    provenance: dict[str, Any] | None = None,
) -> ValidationIssue:
    issue_provenance = {"source_row_id": row.source_row_id} if row else {}
    issue_provenance.update(provenance or {})
    return ValidationIssue(
        category=category,
        reason_code=reason_code,
        severity=severity,
        message=message,
        source_ref=source_ref,
        assist2017_question_id=row.assist2017_question_id if row else None,
        assist2017_concept_id=row.assist2017_concept_id if row else None,
        canonical_question_id=row.question_id if row else None,
        canonical_concept_id=row.concept_id if row else None,
        provenance=issue_provenance,
    )


def _raise_if_needed(issues: list[ValidationIssue], fail_on_errors: bool) -> None:
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors and fail_on_errors:
        raise Assist2017BuildError(errors)


def _required(raw: dict[str, str], key: str) -> str:
    value = _blank_to_none(raw.get(key))
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _split_pipe_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split("|") if item.strip()]


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _display_path(path: str | Path) -> str:
    resolved = Path(path)
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def _resolve_project_path(path: str | Path) -> Path:
    resolved = Path(path)
    if resolved.is_absolute() or resolved.exists():
        return resolved
    return PROJECT_ROOT / resolved
