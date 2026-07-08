from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any


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
        public.pop("standard_answer", None)
        public.pop("explanation", None)
        return public

    def grade(self, question_id: str, submitted_answer: Any) -> GradeResult | None:
        question = self.get_question(question_id)
        if question is None:
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
        enriched.setdefault("assist2017_question_id", assist2017_question_id)
        return enriched

    def _normalize_answer(self, answer: str) -> str:
        return answer.strip().replace(" ", "").replace("，", ",").lower()


content_repository = DemoTeachingContentRepository()
