from __future__ import annotations

from typing import Any

from .schema import RAGSearchResult
from .viking_provider import (
    matches_rag_metadata_filter,
    normalize_rag_metadata_filters,
)


class FakeKnowledgeRAGProvider:
    """Offline VikingDB/OpenViking-shaped fixture normalized to RAGSearchResult."""

    provider_mode = "fake_provider"
    allows_question_to_concept_fallback = True

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        *,
        provider_supports_metadata_filter: bool = True,
    ) -> None:
        self._records = records if records is not None else _fake_provider_records()
        self.provider_supports_metadata_filter = provider_supports_metadata_filter

    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> list[RAGSearchResult]:
        filters = normalize_rag_metadata_filters(filters or {})
        candidates = [
            record
            for record in self._records
            if not self.provider_supports_metadata_filter
            or self._matches_filters(record, filters)
        ]
        terms = self._terms(query)
        scored = [
            (self._score(record, terms), record)
            for record in candidates
        ]
        scored.sort(key=lambda item: (-item[0], item[1]["id"]))
        positive = [(score, record) for score, record in scored if score > 0]
        fetch_limit = max(limit * 5, 10) if filters and not self.provider_supports_metadata_filter else limit
        selected = positive[:fetch_limit] if positive else scored[:fetch_limit]
        results = [
            self._to_domain_result(record, score=score)
            for score, record in selected
        ]
        filtered = [result for result in results if matches_rag_metadata_filter(result, filters)]
        filtered.sort(key=lambda result: (-result.score, result.doc_id))
        return filtered[:limit]

    def _matches_filters(self, record: dict[str, Any], filters: dict[str, Any]) -> bool:
        payload = record["payload"]
        doc_type = filters.get("doc_type")
        if doc_type and payload["doc_type"] != doc_type:
            return False
        doc_types = filters.get("doc_types")
        if doc_types and payload["doc_type"] not in set(doc_types):
            return False
        concept_id = filters.get("concept_id")
        if concept_id and payload.get("concept_id") != concept_id:
            return False
        question_id = filters.get("question_id")
        if question_id and payload.get("question_id") != question_id:
            return False
        assist_question_id = filters.get("assist2017_question_id")
        if assist_question_id and str(payload.get("assist2017_question_id")) != str(
            assist_question_id
        ):
            return False
        assist_concept_id = filters.get("assist2017_concept_id")
        if assist_concept_id and str(payload.get("assist2017_concept_id")) != str(
            assist_concept_id
        ):
            return False
        return True

    def _to_domain_result(self, record: dict[str, Any], *, score: float) -> RAGSearchResult:
        payload = record["payload"]
        return RAGSearchResult(
            doc_id=str(payload["doc_id"]),
            doc_type=payload["doc_type"],
            title=str(payload["title"]),
            content=str(payload["content"]),
            source=str(payload["source"]),
            concept_id=payload.get("concept_id"),
            question_id=payload.get("question_id"),
            assist2017_question_id=payload.get("assist2017_question_id"),
            assist2017_concept_id=payload.get("assist2017_concept_id"),
            canonical_mapping=dict(payload.get("canonical_mapping") or {}),
            provenance={
                "provider_name": "fake_vikingdb",
                "provider_mode": "fake_provider",
                "collection": "fake_rag_contract_fixture",
                "provider_record_id": record["id"],
                "source": payload["source"],
            },
            coverage=dict(payload.get("coverage") or {}),
            score=round(score, 4),
        )

    def _score(self, record: dict[str, Any], terms: set[str]) -> float:
        payload = record["payload"]
        base_score = max(0.0, 1.0 - float(record["vikingdb_distance"]))
        if not terms:
            return base_score
        haystack = self._terms(
            " ".join(
                [
                    str(payload["title"]),
                    str(payload["content"]),
                    " ".join(payload.get("keywords", [])),
                ]
            )
        )
        return base_score + len(terms & haystack)

    def _terms(self, text: str) -> set[str]:
        normalized = (
            text.lower()
            .replace("，", " ")
            .replace("。", " ")
            .replace("？", " ")
            .replace("?", " ")
            .replace(",", " ")
            .replace(".", " ")
        )
        terms = {term.strip() for term in normalized.split() if term.strip()}
        for keyword in ("分数", "通分", "公分母", "错因", "题解", "策略", "推荐"):
            if keyword in normalized:
                terms.add(keyword)
        return terms


def _fake_provider_records() -> list[dict[str, Any]]:
    return [
        _provider_record(
            "fake-vector-001",
            distance=0.08,
            payload={
                "doc_id": "fake-rag-fraction-note",
                "doc_type": "concept_note",
                "title": "分数通分概念说明",
                "content": "通分是把异分母分数转成同分母分数，方便比较或相加。",
                "source": "fake-rag/fraction_concepts.md",
                "concept_id": "c_fraction_addition",
                "question_id": None,
                "assist2017_question_id": None,
                "assist2017_concept_id": 2,
                "canonical_mapping": {
                    "concept_id": "c_fraction_addition",
                    "assist2017_concept_id": 2,
                    "source": "fake_provider_fixture",
                },
                "coverage": {
                    "coverage_type": "concept",
                    "concept_aligned": True,
                },
                "keywords": ["分数", "通分", "公分母"],
            },
        ),
        _provider_record(
            "fake-vector-002",
            distance=0.12,
            payload={
                "doc_id": "fake-rag-q-frac-001-solution",
                "doc_type": "question_explanation",
                "title": "q_frac_001 题解",
                "content": "先找公分母，再把两个分数化成同分母后相加。",
                "source": "fake-rag/question_solutions.md#q_frac_001",
                "concept_id": "c_fraction_addition",
                "question_id": "q_frac_001",
                "assist2017_question_id": 3,
                "assist2017_concept_id": 2,
                "canonical_mapping": {
                    "question_id": "q_frac_001",
                    "concept_id": "c_fraction_addition",
                    "assist2017_question_id": 3,
                    "assist2017_concept_id": 2,
                    "source": "fake_provider_fixture",
                },
                "coverage": {
                    "coverage_type": "question",
                    "question_aligned": True,
                    "concept_aligned": True,
                },
                "keywords": ["题解", "通分", "分数"],
            },
        ),
        _provider_record(
            "fake-vector-003",
            distance=0.16,
            payload={
                "doc_id": "fake-rag-fraction-mistake",
                "doc_type": "mistake_pattern",
                "title": "常见错因：直接相加分母",
                "content": "错因通常是没有先通分，直接把分母相加。",
                "source": "fake-rag/fraction_mistakes.md",
                "concept_id": "c_fraction_addition",
                "question_id": "q_frac_001",
                "assist2017_question_id": 3,
                "assist2017_concept_id": 2,
                "canonical_mapping": {
                    "question_id": "q_frac_001",
                    "concept_id": "c_fraction_addition",
                    "assist2017_question_id": 3,
                    "assist2017_concept_id": 2,
                    "source": "fake_provider_fixture",
                },
                "coverage": {
                    "coverage_type": "question",
                    "question_aligned": True,
                    "concept_aligned": True,
                },
                "keywords": ["错因", "通分", "分母"],
            },
        ),
        _provider_record(
            "fake-vector-004",
            distance=0.2,
            payload={
                "doc_id": "fake-rag-fraction-strategy",
                "doc_type": "learning_strategy",
                "title": "分数题步骤化复习策略",
                "content": "先标出分母，再找公分母，最后检查答案是否可约分。",
                "source": "fake-rag/fraction_strategy.md",
                "concept_id": "c_fraction_addition",
                "question_id": None,
                "assist2017_question_id": None,
                "assist2017_concept_id": 2,
                "canonical_mapping": {
                    "concept_id": "c_fraction_addition",
                    "assist2017_concept_id": 2,
                    "source": "fake_provider_fixture",
                },
                "coverage": {
                    "coverage_type": "concept",
                    "concept_aligned": True,
                },
                "keywords": ["策略", "推荐", "通分"],
            },
        ),
    ]


def _provider_record(
    provider_id: str,
    *,
    distance: float,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": provider_id,
        "payload": payload,
        "sdk_response": {
            "object": "vikingdb.search_result",
            "raw_provider_payload": payload,
        },
        "vikingdb_distance": distance,
        "embedding_vector": [0.11, 0.22, 0.33],
        "provider_debug": {
            "network": "disabled",
            "fixture": True,
        },
    }
