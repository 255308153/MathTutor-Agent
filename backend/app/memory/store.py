from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from ..core.config import MathTutorSettings, get_settings


MemoryType = Literal["preference", "repeated_mistake", "effective_strategy", "reflection"]
MemoryFreshness = Literal["fresh", "recent", "stale"]


class StudentMemory(BaseModel):
    memory_id: str = Field(default_factory=lambda: f"mem-{uuid4().hex[:10]}")
    student_id: str
    memory_type: MemoryType
    content: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    freshness: MemoryFreshness = "fresh"
    source: str = "local_fallback"
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class StudentMemoryStore(Protocol):
    def search(
        self,
        student_id: str,
        query: str,
        memory_types: list[MemoryType] | None = None,
        limit: int = 5,
    ) -> list[StudentMemory]:
        """Search long-term student memories. Mem0 adapter should preserve this seam."""

    def write(self, memory: StudentMemory) -> StudentMemory:
        """Persist one long-term memory item."""

    def list_recent(self, student_id: str, limit: int = 10) -> list[StudentMemory]:
        """Return recent memories for inspection and planning."""


class MemoryProviderConfigurationError(RuntimeError):
    pass


class InMemoryStudentMemoryStore:
    def __init__(self) -> None:
        self._memories_by_student: dict[str, list[StudentMemory]] = {}

    def search(
        self,
        student_id: str,
        query: str,
        memory_types: list[MemoryType] | None = None,
        limit: int = 5,
    ) -> list[StudentMemory]:
        memories = self._memories_by_student.get(student_id, [])
        if memory_types:
            allowed = set(memory_types)
            memories = [memory for memory in memories if memory.memory_type in allowed]
        terms = self._terms(query)
        scored = [(self._score(memory, terms), memory) for memory in memories]
        scored.sort(
            key=lambda item: (
                -item[0],
                _newest_first_sort_value(item[1].updated_at),
                item[1].memory_id,
            )
        )
        return [
            _with_retrieval_metadata(
                memory,
                relevance_score=_normalized_score(score, terms),
                source="local_fallback",
            )
            for score, memory in scored[:limit]
        ]

    def write(self, memory: StudentMemory) -> StudentMemory:
        memories = self._memories_by_student.setdefault(memory.student_id, [])
        now = datetime.now(UTC).isoformat()
        for index, existing in enumerate(memories):
            if memory_dedupe_key(existing) == memory_dedupe_key(memory):
                memories[index] = existing.model_copy(
                    update={
                        "evidence": {**existing.evidence, **memory.evidence},
                        "provenance": _merge_provenance(existing, memory),
                        "updated_at": now,
                        "freshness": "fresh",
                        "source": existing.source or "local_fallback",
                    }
                )
                return memories[index]
        stored = memory.model_copy(update={"source": memory.source or "local_fallback"})
        memories.append(stored)
        return stored

    def list_recent(self, student_id: str, limit: int = 10) -> list[StudentMemory]:
        memories = self._memories_by_student.get(student_id, [])
        recent = sorted(
            memories,
            key=lambda memory: (_newest_first_sort_value(memory.updated_at), memory.memory_id),
        )[:limit]
        return [
            _with_retrieval_metadata(memory, relevance_score=None, source="local_fallback")
            for memory in recent
        ]

    def _score(self, memory: StudentMemory, terms: set[str]) -> float:
        if not terms:
            return 0.1
        haystack = self._terms(
            " ".join([memory.memory_type, memory.content, " ".join(map(str, memory.evidence.values()))])
        )
        return float(len(terms & haystack))

    def _terms(self, text: str) -> set[str]:
        normalized = text.lower().replace("，", " ").replace("。", " ").replace("？", " ")
        terms = {term for term in normalized.split() if term}
        for keyword in ("偏好", "错因", "策略", "反思", "步骤", "比例", "方程", "分数"):
            if keyword in normalized:
                terms.add(keyword)
        return terms


def create_student_memory_store(
    settings: MathTutorSettings | None = None,
) -> StudentMemoryStore:
    active_settings = settings or get_settings()
    if active_settings.memory_provider_mode == "local_fallback":
        return InMemoryStudentMemoryStore()
    if active_settings.memory_provider_mode == "fake_provider":
        from .fake_provider import FakeStudentMemoryProvider

        return FakeStudentMemoryProvider()
    if active_settings.memory_provider_mode == "live_provider":
        if not active_settings.mem0_api_key:
            raise MemoryProviderConfigurationError(
                "MATHTUTOR_MEMORY_PROVIDER_MODE=live_provider 已显式选择 Mem0，"
                "但缺少 MATHTUTOR_MEM0_API_KEY。默认请保持 local_fallback；"
                "只有显式配置 live provider 时才会加载 Mem0 adapter。"
            )
        from .mem0_provider import Mem0StudentMemoryStore

        return Mem0StudentMemoryStore(api_key=active_settings.mem0_api_key)
    raise MemoryProviderConfigurationError(
        f"Unsupported memory provider mode: {active_settings.memory_provider_mode}"
    )


def memory_dedupe_key(memory: StudentMemory) -> str:
    evidence = memory.evidence or {}
    stable_parts = [
        memory.student_id,
        memory.memory_type,
        _normalize_identity_text(memory.content),
        str(evidence.get("question_id") or ""),
        str(evidence.get("concept_id") or ""),
        str(evidence.get("preferred_concept_id") or ""),
        str(evidence.get("preferred_teaching_type") or ""),
    ]
    raw = "|".join(stable_parts)
    return f"memory:{sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def memory_freshness(updated_at: str | None) -> MemoryFreshness:
    if not updated_at:
        return "recent"
    try:
        updated = datetime.fromisoformat(str(updated_at))
    except ValueError:
        return "recent"
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - updated).days
    if age_days <= 7:
        return "fresh"
    if age_days <= 45:
        return "recent"
    return "stale"


def _with_retrieval_metadata(
    memory: StudentMemory,
    *,
    relevance_score: float | None,
    source: str,
) -> StudentMemory:
    return memory.model_copy(
        update={
            "relevance_score": relevance_score,
            "freshness": memory_freshness(memory.updated_at),
            "source": memory.source or source,
        }
    )


def _normalized_score(score: float, terms: set[str]) -> float:
    if not terms:
        return 0.1
    return round(min(max(score / max(len(terms), 1), 0.0), 1.0), 4)


def _newest_first_sort_value(value: str) -> float:
    try:
        return -datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def _merge_provenance(existing: StudentMemory, incoming: StudentMemory) -> dict[str, Any]:
    provenance = {**existing.provenance, **incoming.provenance}
    trace_ids = _unique_values(
        existing.provenance.get("trace_ids"),
        existing.provenance.get("trace_id"),
        incoming.provenance.get("trace_ids"),
        incoming.provenance.get("trace_id"),
        existing.evidence.get("trace_id"),
        incoming.evidence.get("trace_id"),
    )
    event_sources = _unique_values(
        existing.provenance.get("event_sources"),
        existing.provenance.get("source_event"),
        incoming.provenance.get("event_sources"),
        incoming.provenance.get("source_event"),
        existing.evidence.get("source_event"),
        incoming.evidence.get("source_event"),
    )
    event_times = _unique_values(
        existing.provenance.get("event_times"),
        existing.provenance.get("occurred_at"),
        incoming.provenance.get("event_times"),
        incoming.provenance.get("occurred_at"),
        existing.evidence.get("event_time"),
        incoming.evidence.get("event_time"),
    )
    if trace_ids:
        provenance["trace_ids"] = trace_ids
    if event_sources:
        provenance["event_sources"] = event_sources
    if event_times:
        provenance["event_times"] = event_times
    provenance["dedupe_key"] = memory_dedupe_key(incoming)
    return provenance


def _unique_values(*values: Any) -> list[str]:
    items: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            candidates = value
        else:
            candidates = [value]
        for candidate in candidates:
            text = str(candidate)
            if text and text not in items:
                items.append(text)
    return items


def _normalize_identity_text(text: str) -> str:
    return " ".join(str(text).lower().split())


memory_store = create_student_memory_store()
