from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from ..core.config import MathTutorSettings, get_settings


MemoryType = Literal["preference", "repeated_mistake", "effective_strategy", "reflection"]


class StudentMemory(BaseModel):
    memory_id: str = Field(default_factory=lambda: f"mem-{uuid4().hex[:10]}")
    student_id: str
    memory_type: MemoryType
    content: str
    evidence: dict[str, Any] = Field(default_factory=dict)
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
        scored = [
            (self._score(memory, terms), memory)
            for memory in memories
        ]
        scored.sort(key=lambda item: (-item[0], item[1].updated_at))
        return [memory for _, memory in scored[:limit]]

    def write(self, memory: StudentMemory) -> StudentMemory:
        memories = self._memories_by_student.setdefault(memory.student_id, [])
        now = datetime.now(UTC).isoformat()
        for index, existing in enumerate(memories):
            if (
                existing.memory_type == memory.memory_type
                and existing.content == memory.content
            ):
                memories[index] = existing.model_copy(update={"evidence": memory.evidence, "updated_at": now})
                return memories[index]
        memories.append(memory)
        return memory

    def list_recent(self, student_id: str, limit: int = 10) -> list[StudentMemory]:
        memories = self._memories_by_student.get(student_id, [])
        return sorted(memories, key=lambda memory: memory.updated_at, reverse=True)[:limit]

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
        raise MemoryProviderConfigurationError(
            "MATHTUTOR_MEMORY_PROVIDER_MODE=live_provider 已显式选择 Mem0 live provider，"
            "但 V1.7 #71 只固定 contract，不加载 Mem0 SDK。请保持 local_fallback，"
            "或在后续 Mem0 adapter issue 中接入真实 provider。"
        )
    raise MemoryProviderConfigurationError(
        f"Unsupported memory provider mode: {active_settings.memory_provider_mode}"
    )


memory_store = create_student_memory_store()
