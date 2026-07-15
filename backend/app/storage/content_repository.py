from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol

from ..core.config import MathTutorSettings, get_settings
from ..importing.xes3g5m_artifacts import ContentImportArtifact
from ..mapping.xes3g5m_mapping import CanonicalMappingRepository, DEFAULT_MAPPING_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONTENT_PATH = PROJECT_ROOT / "data" / "content" / "demo_teaching_content.json"


@dataclass(frozen=True)
class GradeResult:
    question: dict[str, Any]
    submitted_answer: str
    normalized_answer: str
    normalized_standard_answer: str
    is_correct: bool


class ContentRepository(Protocol):
    grading_source: str

    def teaching_type_for(self, concept_id: str) -> str: ...

    def list_questions(self) -> list[dict[str, Any]]: ...

    def get_question(self, question_id: str) -> dict[str, Any] | None: ...

    def first_recommendable_question(self) -> dict[str, Any]: ...

    def public_question(self, question: dict[str, Any]) -> dict[str, Any]: ...

    def grade(self, question_id: str, submitted_answer: Any) -> GradeResult | None: ...

    def content_availability(self, question: dict[str, Any]) -> dict[str, Any]: ...

    def provenance(self, question: dict[str, Any]) -> dict[str, Any]: ...


class ContentArtifactConfigurationError(RuntimeError):
    pass


class BaseTeachingContentRepository:
    grading_source = "teaching_content"

    def first_recommendable_question(self) -> dict[str, Any]:
        return self.list_questions()[0]

    def public_question(self, question: dict[str, Any]) -> dict[str, Any]:
        public = dict(question)
        standard_answer = public.pop("standard_answer", None)
        availability = self.content_availability(question)
        if public.get("stem") in (None, ""):
            public["stem"] = availability["fallback_message"] or "题干暂缺，请补齐教学内容。"
        public["answer"] = standard_answer
        public["explanation"] = question.get("explanation")
        public["content_availability"] = availability
        public["provenance"] = self.provenance(question)
        return public

    def grade(self, question_id: str, submitted_answer: Any) -> GradeResult | None:
        question = self.get_question(question_id)
        if question is None:
            return None
        if "standard_answer" not in question or question["standard_answer"] in (None, ""):
            return None
        submitted = "" if submitted_answer is None else str(submitted_answer)
        normalized_answer = self._normalize_answer(submitted)
        normalized_standard = self._normalize_answer(question["standard_answer"])
        return GradeResult(
            question=question,
            submitted_answer=submitted,
            normalized_answer=normalized_answer,
            normalized_standard_answer=normalized_standard,
            is_correct=normalized_answer == normalized_standard,
        )

    def content_availability(self, question: dict[str, Any]) -> dict[str, Any]:
        required_fields = {
            "stem": "题干",
            "standard_answer": "标准答案",
            "explanation": "解析",
        }
        missing_fields = [
            field for field in required_fields if question.get(field) in (None, "")
        ]
        has_concept_metadata = bool(question.get("concept_id") and question.get("concept_name"))
        if not has_concept_metadata:
            missing_fields.append("concept_metadata")

        existing = question.get("content_availability")
        existing_reason_codes = list((existing or {}).get("missing_reason_codes", []))
        reason_codes = [
            *existing_reason_codes,
            *(
                f"missing_{field}"
                for field in missing_fields
                if f"missing_{field}" not in set(existing_reason_codes)
            ),
        ]
        fallback_message = (existing or {}).get("fallback_message") or self._fallback_message(
            question,
            missing_fields,
        )
        return {
            "status": "available" if not missing_fields else "partial",
            "has_stem": "stem" not in missing_fields,
            "has_answer": "standard_answer" not in missing_fields,
            "has_explanation": "explanation" not in missing_fields,
            "has_concept_metadata": has_concept_metadata,
            "missing_fields": missing_fields,
            "missing_labels": [
                required_fields.get(field, "知识点元数据") for field in missing_fields
            ],
            "missing_reason_codes": reason_codes,
            "fallback_message": fallback_message,
        }

    def provenance(self, question: dict[str, Any]) -> dict[str, Any]:
        return dict(question.get("provenance", {}))

    def _fallback_message(self, question: dict[str, Any], missing_fields: list[str]) -> str | None:
        if not missing_fields:
            return None
        labels = "、".join(
            {
                "stem": "题干",
                "standard_answer": "标准答案",
                "explanation": "解析",
                "concept_metadata": "知识点元数据",
            }[field]
            for field in missing_fields
        )
        question_id = question.get("question_id", "unknown")
        return f"{question_id} 缺少{labels}，请补齐教学内容后再用于完整练习。"

    def _normalize_answer(self, answer: str) -> str:
        return answer.strip().replace(" ", "").replace("，", ",").lower()


class DemoTeachingContentRepository(BaseTeachingContentRepository):
    grading_source = "demo_teaching_content"

    @cached_property
    def content(self) -> dict[str, Any]:
        return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))

    @cached_property
    def canonical_mapping(self) -> CanonicalMappingRepository | None:
        if not DEFAULT_MAPPING_PATH.is_file():
            return None
        return CanonicalMappingRepository.from_path(DEFAULT_MAPPING_PATH)

    def teaching_type_for(self, concept_id: str) -> str:
        return self.content["concept_teaching_type_map"].get(concept_id, "concept")

    def list_questions(self) -> list[dict[str, Any]]:
        return [
            self._with_teaching_type(question, xes3g5m_question_id=index + 1)
            for index, question in enumerate(self.content["questions"])
        ]

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        for question in self.list_questions():
            if question["question_id"] == question_id:
                return question
        return None

    def provenance(self, question: dict[str, Any]) -> dict[str, Any]:
        mapping_source = question.get("canonical_mapping_source", "local_sequence_fallback")
        return {
            "content_source": str(CONTENT_PATH.relative_to(PROJECT_ROOT)),
            "mapping_source": mapping_source,
            "xes3g5m_question_id": question.get("xes3g5m_question_id"),
            "xes3g5m_concept_id": question.get("xes3g5m_concept_id"),
            "kc_routes_reference": question.get("kc_routes_reference"),
            "answer_source": (
                "demo_teaching_content.standard_answer"
                if question.get("standard_answer") not in (None, "")
                else None
            ),
            "explanation_source": (
                "demo_teaching_content.explanation"
                if question.get("explanation") not in (None, "")
                else None
            ),
        }

    def _with_teaching_type(
        self,
        question: dict[str, Any],
        *,
        xes3g5m_question_id: int,
    ) -> dict[str, Any]:
        enriched = dict(question)
        enriched["teaching_type"] = self.teaching_type_for(question["concept_id"])
        canonical = None
        if self.canonical_mapping is not None:
            canonical = self.canonical_mapping.get_by_mathtutor_question_id(question["question_id"])
        if canonical is not None:
            enriched["xes3g5m_question_id"] = canonical.xes3g5m_question_id
            if canonical.xes3g5m_concept_id is not None:
                enriched["xes3g5m_concept_id"] = canonical.xes3g5m_concept_id
            enriched["canonical_mapping_source"] = canonical.source_provenance.source
            enriched["kc_routes_reference"] = canonical.kc_routes_reference.model_dump()
        else:
            enriched.setdefault("xes3g5m_question_id", xes3g5m_question_id)
        enriched["content_availability"] = self.content_availability(enriched)
        enriched["provenance"] = self.provenance(enriched)
        return enriched


class ImportedTeachingContentRepository(BaseTeachingContentRepository):
    grading_source = "xes3g5m_content_import"

    def __init__(self, artifact_path: str | Path) -> None:
        self.artifact_path = Path(artifact_path)

    @cached_property
    def artifact(self) -> ContentImportArtifact:
        path = _resolve_project_path(self.artifact_path)
        if not path.is_file():
            raise ContentArtifactConfigurationError(
                "MATHTUTOR_CONTENT_SOURCE=imported 需要配置有效的 "
                f"MATHTUTOR_CONTENT_IMPORT_PATH；当前找不到 {self.artifact_path}。"
            )
        return ContentImportArtifact.model_validate_json(path.read_text(encoding="utf-8"))

    @cached_property
    def content(self) -> dict[str, Any]:
        return self.artifact.model_dump()

    def teaching_type_for(self, concept_id: str) -> str:
        return self.artifact.concept_teaching_type_map.get(concept_id, "concept")

    def list_questions(self) -> list[dict[str, Any]]:
        return [self._normalize_imported_question(question) for question in self.artifact.questions]

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        for question in self.list_questions():
            if question["question_id"] == question_id:
                return question
        return None

    def provenance(self, question: dict[str, Any]) -> dict[str, Any]:
        path = _resolve_project_path(self.artifact_path)
        question_provenance = dict(question.get("provenance", {}))
        return {
            "content_source": _display_path(path),
            "mapping_source": question.get("canonical_mapping_source", "xes3g5m_import"),
            "xes3g5m_question_id": question.get("xes3g5m_question_id"),
            "xes3g5m_concept_id": question.get("xes3g5m_concept_id"),
            "kc_routes_reference": question.get("kc_routes_reference"),
            "answer_source": question_provenance.get("answer_source"),
            "explanation_source": question_provenance.get("explanation_source"),
            "source_row_id": question_provenance.get("source_row_id"),
            "import_metadata": {
                "generated_at": self.artifact.metadata.generated_at,
                "source_paths": self.artifact.metadata.source_paths,
                "row_counts": self.artifact.metadata.row_counts,
            },
        }

    def _normalize_imported_question(self, question: Any) -> dict[str, Any]:
        raw = question.model_dump()
        canonical = dict(raw.get("canonical_mapping", {}))
        raw["teaching_type"] = raw.get("teaching_type") or self.teaching_type_for(raw["concept_id"])
        raw["canonical_mapping_source"] = canonical.get("source", "xes3g5m_import")
        raw["kc_routes_reference"] = raw.get("kc_routes_reference") or canonical.get(
            "kc_routes_reference"
        )
        availability = self.content_availability(raw)
        raw["content_availability"] = availability
        raw["provenance"] = self.provenance(raw)
        return raw


def create_content_repository(settings: MathTutorSettings | None = None) -> ContentRepository:
    active_settings = settings or get_settings()
    if active_settings.content_source == "demo":
        return DemoTeachingContentRepository()
    if active_settings.content_source == "imported":
        if not active_settings.content_import_path:
            raise ContentArtifactConfigurationError(
                "MATHTUTOR_CONTENT_SOURCE=imported 时必须设置 "
                "MATHTUTOR_CONTENT_IMPORT_PATH 指向 content_import.json。"
            )
        return ImportedTeachingContentRepository(active_settings.content_import_path)
    raise ContentArtifactConfigurationError(
        f"Unsupported content source: {active_settings.content_source}"
    )


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _resolve_project_path(path: str | Path) -> Path:
    resolved = Path(path)
    if resolved.is_absolute() or resolved.exists():
        return resolved
    return PROJECT_ROOT / resolved


content_repository = create_content_repository()

