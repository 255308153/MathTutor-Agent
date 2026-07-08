from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from ..mapping.assist2017_mapping import CanonicalMappingRepository, DEFAULT_MAPPING_PATH


CONTENT_PATH = Path(__file__).resolve().parents[3] / "data" / "content" / "demo_teaching_content.json"


@dataclass(frozen=True)
class GradeResult:
    question: dict[str, Any]
    submitted_answer: str
    normalized_answer: str
    normalized_standard_answer: str
    is_correct: bool


class DemoTeachingContentRepository:
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
            self._with_teaching_type(question, assist2017_question_id=index + 1)
            for index, question in enumerate(self.content["questions"])
        ]

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        for question in self.list_questions():
            if question["question_id"] == question_id:
                return question
        return None

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

    def _with_teaching_type(
        self,
        question: dict[str, Any],
        *,
        assist2017_question_id: int,
    ) -> dict[str, Any]:
        enriched = dict(question)
        enriched["teaching_type"] = self.teaching_type_for(question["concept_id"])
        canonical = None
        if self.canonical_mapping is not None:
            canonical = self.canonical_mapping.get_by_mathtutor_question_id(question["question_id"])
        if canonical is not None:
            enriched["assist2017_question_id"] = canonical.assist2017_question_id
            if canonical.assist2017_concept_id is not None:
                enriched["assist2017_concept_id"] = canonical.assist2017_concept_id
            enriched["canonical_mapping_source"] = canonical.source_provenance.source
            enriched["q_matrix_reference"] = canonical.q_matrix_reference.model_dump()
        else:
            enriched.setdefault("assist2017_question_id", assist2017_question_id)
        enriched["content_availability"] = self.content_availability(enriched)
        enriched["provenance"] = self.provenance(enriched)
        return enriched

    def content_availability(self, question: dict[str, Any]) -> dict[str, Any]:
        required_fields = {
            "stem": "题干",
            "standard_answer": "标准答案",
            "explanation": "解析",
        }
        missing_fields = [
            field
            for field in required_fields
            if question.get(field) in (None, "")
        ]
        return {
            "status": "available" if not missing_fields else "partial",
            "has_stem": "stem" not in missing_fields,
            "has_answer": "standard_answer" not in missing_fields,
            "has_explanation": "explanation" not in missing_fields,
            "missing_fields": missing_fields,
            "missing_labels": [required_fields[field] for field in missing_fields],
            "fallback_message": self._fallback_message(question, missing_fields),
        }

    def provenance(self, question: dict[str, Any]) -> dict[str, Any]:
        mapping_source = question.get("canonical_mapping_source", "local_sequence_fallback")
        return {
            "content_source": str(CONTENT_PATH.relative_to(CONTENT_PATH.parents[2])),
            "mapping_source": mapping_source,
            "assist2017_question_id": question.get("assist2017_question_id"),
            "assist2017_concept_id": question.get("assist2017_concept_id"),
            "q_matrix_reference": question.get("q_matrix_reference"),
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

    def _fallback_message(self, question: dict[str, Any], missing_fields: list[str]) -> str | None:
        if not missing_fields:
            return None
        labels = "、".join(
            {
                "stem": "题干",
                "standard_answer": "标准答案",
                "explanation": "解析",
            }[field]
            for field in missing_fields
        )
        question_id = question.get("question_id", "unknown")
        return f"{question_id} 缺少{labels}，请补齐教学内容后再用于完整练习。"

    def _normalize_answer(self, answer: str) -> str:
        return answer.strip().replace(" ", "").replace("，", ",").lower()


content_repository = DemoTeachingContentRepository()
