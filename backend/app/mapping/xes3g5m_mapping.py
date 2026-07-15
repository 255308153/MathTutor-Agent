from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAPPING_PATH = PROJECT_ROOT / "data" / "mapping" / "xes3g5m_canonical_mapping.fixture.json"
SCHEMA_VERSION = "xes3g5m-canonical-mapping/v1"


class MappingProvenance(BaseModel):
    source: str
    confidence: Literal["curated", "derived", "fixture", "unknown"] = "unknown"
    notes: str | None = None


class KCRoutesReference(BaseModel):
    kc_routes_path: str
    row_index: int = Field(ge=1)
    concept_column_indices: list[int] = Field(min_length=1)

    @field_validator("concept_column_indices")
    @classmethod
    def concept_columns_are_positive(cls, value: list[int]) -> list[int]:
        if any(column < 1 for column in value):
            raise ValueError("KC routes concept columns are 1-based and must be positive.")
        return value


class CanonicalConceptMapping(BaseModel):
    xes3g5m_concept_id: int = Field(ge=1)
    concept_id: str = Field(min_length=1)
    concept_name: str = Field(min_length=1)
    teaching_type: str = Field(min_length=1)
    source_provenance: MappingProvenance


class CanonicalQuestionMapping(BaseModel):
    xes3g5m_question_id: int = Field(ge=1)
    question_id: str = Field(min_length=1)
    concept_id: str = Field(min_length=1)
    concept_name: str = Field(min_length=1)
    teaching_type: str = Field(min_length=1)
    kc_routes_reference: KCRoutesReference
    source_provenance: MappingProvenance
    xes3g5m_concept_id: int | None = Field(default=None, ge=1)
    rag_doc_ids: list[str] = Field(default_factory=list)


class KCRoutesArtifactSummary(BaseModel):
    source_path: str
    row_base: Literal[1] = 1
    column_base: Literal[1] = 1
    question_count: int = Field(ge=0)
    concept_count: int = Field(ge=0)


class CanonicalMappingArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["xes3g5m-canonical-mapping/v1"] = SCHEMA_VERSION
    dataset: Literal["xes3g5m"] = "xes3g5m"
    generated_at: str
    kc_routes: KCRoutesArtifactSummary
    concepts: list[CanonicalConceptMapping]
    questions: list[CanonicalQuestionMapping]

    @model_validator(mode="after")
    def validate_unique_and_aligned(self) -> CanonicalMappingArtifact:
        concept_ids = [concept.xes3g5m_concept_id for concept in self.concepts]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("Duplicate xes3g5m_concept_id in canonical mapping.")

        local_concept_ids = [concept.concept_id for concept in self.concepts]
        if len(local_concept_ids) != len(set(local_concept_ids)):
            raise ValueError("Duplicate local concept_id in canonical mapping.")

        question_ids = [question.xes3g5m_question_id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Duplicate xes3g5m_question_id in canonical mapping.")

        local_question_ids = [question.question_id for question in self.questions]
        if len(local_question_ids) != len(set(local_question_ids)):
            raise ValueError("Duplicate local question_id in canonical mapping.")

        concepts_by_local_id = {concept.concept_id: concept for concept in self.concepts}
        for question in self.questions:
            concept = concepts_by_local_id.get(question.concept_id)
            if concept is None:
                raise ValueError(
                    f"Question {question.question_id} references unknown concept_id "
                    f"{question.concept_id}."
                )
            if question.xes3g5m_concept_id is not None:
                if question.xes3g5m_concept_id != concept.xes3g5m_concept_id:
                    raise ValueError(
                        f"Question {question.question_id} concept mapping is inconsistent "
                        "with the concept table."
                    )
                if question.xes3g5m_concept_id not in question.kc_routes_reference.concept_column_indices:
                    raise ValueError(
                        f"Question {question.question_id} concept mapping is not present in "
                        "its KC routes row."
                    )
        return self


class MappingCoverageDiagnostics(BaseModel):
    mapped_questions: list[int]
    mapped_concepts: list[int]
    missing_questions: list[int]
    missing_concepts: list[int]
    missing_teaching_content: list[str]
    missing_rag_docs: list[str]

    @property
    def mapped_question_count(self) -> int:
        return len(self.mapped_questions)

    @property
    def mapped_concept_count(self) -> int:
        return len(self.mapped_concepts)

    def to_report(self) -> dict[str, Any]:
        return {
            "mapped_question_count": self.mapped_question_count,
            "mapped_concept_count": self.mapped_concept_count,
            "mapped_questions": self.mapped_questions,
            "mapped_concepts": self.mapped_concepts,
            "missing_questions": self.missing_questions,
            "missing_concepts": self.missing_concepts,
            "missing_teaching_content": self.missing_teaching_content,
            "missing_rag_docs": self.missing_rag_docs,
        }


class CanonicalMappingRepository:
    def __init__(self, artifact: CanonicalMappingArtifact) -> None:
        self.artifact = artifact
        self._questions_by_local_id = {question.question_id: question for question in artifact.questions}
        self._questions_by_assist_id = {
            question.xes3g5m_question_id: question for question in artifact.questions
        }
        self._concepts_by_local_id = {concept.concept_id: concept for concept in artifact.concepts}
        self._concepts_by_assist_id = {
            concept.xes3g5m_concept_id: concept for concept in artifact.concepts
        }

    @classmethod
    def from_path(cls, path: str | Path = DEFAULT_MAPPING_PATH) -> CanonicalMappingRepository:
        return cls(load_mapping_artifact(path))

    def get_by_mathtutor_question_id(self, question_id: str) -> CanonicalQuestionMapping | None:
        return self._questions_by_local_id.get(question_id)

    def get_by_xes3g5m_question_id(
        self, xes3g5m_question_id: int
    ) -> CanonicalQuestionMapping | None:
        return self._questions_by_assist_id.get(xes3g5m_question_id)

    def concept_for_mathtutor_concept_id(self, concept_id: str) -> CanonicalConceptMapping | None:
        return self._concepts_by_local_id.get(concept_id)

    def concept_for_xes3g5m_concept_id(
        self, xes3g5m_concept_id: int
    ) -> CanonicalConceptMapping | None:
        return self._concepts_by_assist_id.get(xes3g5m_concept_id)

    def coverage(
        self,
        *,
        kc_routes_path: str | Path | None = None,
        teaching_content: dict[str, Any] | None = None,
        rag_docs: list[dict[str, Any]] | None = None,
    ) -> MappingCoverageDiagnostics:
        return coverage_diagnostics(
            self.artifact,
            kc_routes_path=kc_routes_path,
            teaching_content=teaching_content,
            rag_docs=rag_docs,
        )


def load_mapping_artifact(path: str | Path = DEFAULT_MAPPING_PATH) -> CanonicalMappingArtifact:
    raw = json.loads(_resolve_project_path(path).read_text(encoding="utf-8"))
    return CanonicalMappingArtifact.model_validate(raw)


def build_mapping_artifact(
    *,
    kc_routes_path: str | Path,
    metadata_path: str | Path,
    teaching_content_path: str | Path | None = None,
    rag_docs_path: str | Path | None = None,
    output_path: str | Path | None = None,
    generated_at: str | None = None,
) -> CanonicalMappingArtifact:
    q_rows = read_kc_routes(kc_routes_path)
    metadata = json.loads(_resolve_project_path(metadata_path).read_text(encoding="utf-8"))
    teaching_content = _load_json_object(teaching_content_path) if teaching_content_path else None
    rag_docs = _load_json_list(rag_docs_path) if rag_docs_path else None

    concepts = [
        CanonicalConceptMapping.model_validate(concept)
        for concept in metadata.get("concepts", [])
    ]
    concepts_by_assist_id = {concept.xes3g5m_concept_id: concept for concept in concepts}

    questions: list[CanonicalQuestionMapping] = []
    for question in metadata.get("questions", []):
        assist_question_id = int(question["xes3g5m_question_id"])
        if assist_question_id < 1 or assist_question_id > len(q_rows):
            raise ValueError(
                f"Question {assist_question_id} is outside KC routes row range 1..{len(q_rows)}."
            )
        concept_columns = q_rows[assist_question_id - 1]
        assist_concept_id = int(question["xes3g5m_concept_id"])
        if assist_concept_id not in concept_columns:
            raise ValueError(
                f"Question {assist_question_id} declares xes3g5m_concept_id "
                f"{assist_concept_id}, but KC routes row has {concept_columns}."
            )
        if assist_concept_id not in concepts_by_assist_id:
            raise ValueError(
                f"Question {assist_question_id} declares unknown xes3g5m_concept_id "
                f"{assist_concept_id}."
            )

        enriched = dict(question)
        enriched["kc_routes_reference"] = {
            "kc_routes_path": _display_path(kc_routes_path),
            "row_index": assist_question_id,
            "concept_column_indices": concept_columns,
        }
        questions.append(CanonicalQuestionMapping.model_validate(enriched))

    artifact = CanonicalMappingArtifact(
        generated_at=generated_at or datetime.now(UTC).isoformat(),
        kc_routes=KCRoutesArtifactSummary(
            source_path=_display_path(kc_routes_path),
            question_count=len(q_rows),
            concept_count=max((max(row) for row in q_rows if row), default=0),
        ),
        concepts=concepts,
        questions=questions,
    )

    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(artifact.model_dump(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if teaching_content is not None or rag_docs is not None:
        # Validate the optional local context eagerly so import failures are reproducible.
        coverage_diagnostics(artifact, kc_routes_path=kc_routes_path, teaching_content=teaching_content, rag_docs=rag_docs)

    return artifact


def coverage_diagnostics(
    artifact: CanonicalMappingArtifact,
    *,
    kc_routes_path: str | Path | None = None,
    teaching_content: dict[str, Any] | None = None,
    rag_docs: list[dict[str, Any]] | None = None,
) -> MappingCoverageDiagnostics:
    q_rows = read_kc_routes(kc_routes_path or artifact.kc_routes.source_path)
    kc_routes_questions = set(range(1, len(q_rows) + 1))
    kc_routes_concepts = {concept_id for row in q_rows for concept_id in row}

    mapped_questions = {question.xes3g5m_question_id for question in artifact.questions}
    mapped_concepts = {concept.xes3g5m_concept_id for concept in artifact.concepts}

    local_question_ids = _local_question_ids(teaching_content)
    rag_doc_ids = _rag_doc_ids(rag_docs)
    missing_teaching_content = sorted(
        question.question_id
        for question in artifact.questions
        if local_question_ids is not None and question.question_id not in local_question_ids
    )
    missing_rag_docs = sorted(
        {
            doc_id
            for question in artifact.questions
            for doc_id in question.rag_doc_ids
            if rag_doc_ids is not None and doc_id not in rag_doc_ids
        }
    )

    return MappingCoverageDiagnostics(
        mapped_questions=sorted(mapped_questions),
        mapped_concepts=sorted(mapped_concepts),
        missing_questions=sorted(kc_routes_questions - mapped_questions),
        missing_concepts=sorted(kc_routes_concepts - mapped_concepts),
        missing_teaching_content=missing_teaching_content,
        missing_rag_docs=missing_rag_docs,
    )


def read_kc_routes(path: str | Path) -> list[list[int]]:
    rows: list[list[int]] = []
    with _resolve_project_path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        for row_number, row in enumerate(reader, start=1):
            if not row:
                continue
            active_columns: list[int] = []
            for column_index, raw_value in enumerate(row, start=1):
                value = raw_value.strip()
                if value in {"", "0"}:
                    continue
                if value != "1":
                    raise ValueError(
                        f"KC routes only supports 0/1 incidence values; got {value!r} "
                        f"at row {row_number}, column {column_index}."
                    )
                active_columns.append(column_index)
            rows.append(active_columns)
    return rows


def _load_json_object(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    raw = json.loads(_resolve_project_path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected JSON object at {path}.")
    return raw


def _load_json_list(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    raw = json.loads(_resolve_project_path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected JSON array at {path}.")
    return raw


def _local_question_ids(teaching_content: dict[str, Any] | None) -> set[str] | None:
    if teaching_content is None:
        return None
    return {
        str(question["question_id"])
        for question in teaching_content.get("questions", [])
        if "question_id" in question
    }


def _rag_doc_ids(rag_docs: list[dict[str, Any]] | None) -> set[str] | None:
    if rag_docs is None:
        return None
    return {str(document["doc_id"]) for document in rag_docs if "doc_id" in document}


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
