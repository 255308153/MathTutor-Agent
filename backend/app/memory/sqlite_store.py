from __future__ import annotations

from datetime import UTC, datetime

from .store import (
    MemoryType,
    StudentMemory,
    apply_memory_control,
    apply_memory_delete,
    memory_freshness,
)
from ..storage.sqlite_store import SqliteLearningStore, get_learning_store


class SqliteStudentMemoryStore:
    """Durable local memory store used by default local_fallback mode."""

    def __init__(self, store: SqliteLearningStore | None = None) -> None:
        self._store = store or get_learning_store()
        self.last_evidence_gaps: list[dict] = []

    def search(
        self,
        student_id: str,
        query: str,
        memory_types: list[MemoryType] | None = None,
        limit: int = 5,
    ) -> list[StudentMemory]:
        self.last_evidence_gaps = []
        memories = [
            memory
            for memory in self._store.list_memories(student_id)
            if memory.enabled and memory.status == "enabled"
        ]
        if memory_types:
            allowed = set(memory_types)
            memories = [memory for memory in memories if memory.memory_type in allowed]
        terms = _terms(query)
        scored = [(_score(memory, terms), memory) for memory in memories]
        scored.sort(
            key=lambda item: (
                -item[0],
                -_timestamp(item[1].updated_at),
                item[1].memory_id,
            )
        )
        return [
            memory.model_copy(
                update={
                    "relevance_score": _normalized_score(score, terms),
                    "freshness": memory_freshness(memory.updated_at),
                    "source": memory.source or "local_fallback",
                }
            )
            for score, memory in scored[:limit]
        ]

    def write(self, memory: StudentMemory) -> StudentMemory:
        self.last_evidence_gaps = []
        return self._store.write_memory(memory)

    def list_recent(self, student_id: str, limit: int = 10) -> list[StudentMemory]:
        self.last_evidence_gaps = []
        memories = sorted(
            self._store.list_memories(student_id),
            key=lambda memory: (-_timestamp(memory.updated_at), memory.memory_id),
        )[:limit]
        return [
            memory.model_copy(
                update={
                    "relevance_score": None,
                    "freshness": memory_freshness(memory.updated_at),
                    "source": memory.source or "local_fallback",
                }
            )
            for memory in memories
        ]

    def get(self, student_id: str, memory_id: str) -> StudentMemory | None:
        self.last_evidence_gaps = []
        memory = self._store.get_memory(student_id, memory_id)
        if memory is None:
            return None
        return memory.model_copy(
            update={
                "relevance_score": None,
                "freshness": memory_freshness(memory.updated_at),
                "source": memory.source or "local_fallback",
            }
        )

    def disable(
        self,
        student_id: str,
        memory_id: str,
        *,
        actor: str = "student",
        reason: str | None = None,
    ) -> StudentMemory | None:
        return self._set_enabled(
            student_id=student_id,
            memory_id=memory_id,
            enabled=False,
            actor=actor,
            reason=reason,
        )

    def enable(
        self,
        student_id: str,
        memory_id: str,
        *,
        actor: str = "student",
        reason: str | None = None,
    ) -> StudentMemory | None:
        return self._set_enabled(
            student_id=student_id,
            memory_id=memory_id,
            enabled=True,
            actor=actor,
            reason=reason,
        )

    def delete(
        self,
        student_id: str,
        memory_id: str,
        *,
        actor: str = "student",
        reason: str | None = None,
    ) -> StudentMemory | None:
        memory = self._store.get_memory(student_id, memory_id)
        if memory is None:
            # may already be tombstoned; load including deleted via list
            all_memories = self._store.list_memories(student_id, include_deleted=True)
            memory = next((item for item in all_memories if item.memory_id == memory_id), None)
            if memory is None:
                return None
        deleted = apply_memory_delete(memory, actor=actor, reason=reason)
        return self._store.update_memory(deleted)

    def _set_enabled(
        self,
        *,
        student_id: str,
        memory_id: str,
        enabled: bool,
        actor: str,
        reason: str | None,
    ) -> StudentMemory | None:
        memory = self._store.get_memory(student_id, memory_id)
        if memory is None:
            return None
        controlled = apply_memory_control(
            memory,
            enabled=enabled,
            actor=actor,
            reason=reason,
        )
        return self._store.update_memory(controlled)


def _score(memory: StudentMemory, terms: set[str]) -> float:
    if not terms:
        return 0.1
    haystack = _terms(
        " ".join(
            [memory.memory_type, memory.content, " ".join(map(str, memory.evidence.values()))]
        )
    )
    return float(len(terms & haystack))


def _terms(text: str) -> set[str]:
    normalized = text.lower().replace("，", " ").replace("。", " ").replace("？", " ")
    terms = {term for term in normalized.split() if term}
    for keyword in ("偏好", "错因", "策略", "反思", "步骤", "比例", "方程", "分数"):
        if keyword in normalized:
            terms.add(keyword)
    return terms


def _normalized_score(score: float, terms: set[str]) -> float:
    if not terms:
        return 0.1
    return round(min(max(score / max(len(terms), 1), 0.0), 1.0), 4)


def _timestamp(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()
