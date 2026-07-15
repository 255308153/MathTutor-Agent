from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..memory.store import MemoryFreshness, MemoryStatus, MemoryType, StudentMemory


PRIVATE_PROVIDER_KEYS = {
    "api_key",
    "credential",
    "credentials",
    "embedding",
    "embedding_vector",
    "mem0_internal_id",
    "password",
    "provider_debug",
    "raw_provider_payload",
    "sdk_response",
    "secret",
    "token",
    "vector",
}


class StudentMemoryView(BaseModel):
    memory_id: str
    memory_type: MemoryType
    content: str
    summary: str
    source: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    freshness: MemoryFreshness
    enabled: bool
    status: MemoryStatus


class StudentMemoryListResponse(BaseModel):
    student_id: str
    count: int
    memories: list[StudentMemoryView] = Field(default_factory=list)


class StudentMemoryDetailResponse(BaseModel):
    student_id: str
    memory: StudentMemoryView


class StudentMemoryControlRequest(BaseModel):
    actor: str = "student"
    reason: str | None = None


def public_memory_view(memory: StudentMemory) -> StudentMemoryView:
    return StudentMemoryView(
        memory_id=memory.memory_id,
        memory_type=memory.memory_type,
        content=memory.content,
        summary=memory.summary or memory.content,
        source=memory.source,
        evidence=_sanitize_public_value(memory.evidence),
        provenance=_sanitize_public_value(memory.provenance),
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        freshness=memory.freshness,
        enabled=memory.enabled,
        status=memory.status,
    )


def _sanitize_public_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_private_provider_key(key_text):
                continue
            sanitized[key_text] = _sanitize_public_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_public_value(item) for item in value]
    return value


def _is_private_provider_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in PRIVATE_PROVIDER_KEYS or "embedding" in normalized
