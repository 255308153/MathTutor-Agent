from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .store import MemoryStatus, MemoryType, StudentMemory, memory_freshness


class FakeStudentMemoryProvider:
    """Offline Mem0-shaped fixture that returns stable MathTutor memory models."""

    provider_mode = "fake_provider"

    def __init__(self, seed_memories: list[StudentMemory] | None = None) -> None:
        self._records_by_student: dict[str, list[dict[str, Any]]] = {}
        for memory in seed_memories or []:
            self.write(memory)

    def search(
        self,
        student_id: str,
        query: str,
        memory_types: list[MemoryType] | None = None,
        limit: int = 5,
    ) -> list[StudentMemory]:
        records = list(self._records_by_student.get(student_id, []))
        if memory_types:
            allowed = set(memory_types)
            records = [
                record
                for record in records
                if record["metadata"].get("memory_type") in allowed
            ]
        terms = self._terms(query)
        scored = [
            (self._score(record, terms), record)
            for record in records
        ]
        scored.sort(
            key=lambda item: (
                -item[0],
                item[1]["metadata"].get("updated_at", ""),
                item[1]["provider_id"],
            )
        )
        return [
            self._to_domain_memory(record | {"score": score})
            for score, record in scored[:limit]
        ]

    def write(self, memory: StudentMemory) -> StudentMemory:
        records = self._records_by_student.setdefault(memory.student_id, [])
        now = datetime.now(UTC).isoformat()
        for index, existing in enumerate(records):
            if (
                existing["metadata"].get("memory_type") == memory.memory_type
                and existing["memory"] == memory.content
            ):
                updated = self._to_provider_record(
                    memory.model_copy(
                        update={
                            "memory_id": existing["provider_id"],
                            "updated_at": now,
                        }
                    )
                )
                records[index] = updated
                return self._to_domain_memory(updated)
        record = self._to_provider_record(memory)
        records.append(record)
        return self._to_domain_memory(record)

    def list_recent(self, student_id: str, limit: int = 10) -> list[StudentMemory]:
        records = self._records_by_student.get(student_id, [])
        sorted_records = sorted(
            records,
            key=lambda record: (
                record["metadata"].get("updated_at", ""),
                record["provider_id"],
            ),
            reverse=True,
        )
        return [self._to_domain_memory(record) for record in sorted_records[:limit]]

    def get(self, student_id: str, memory_id: str) -> StudentMemory | None:
        for record in self._records_by_student.get(student_id, []):
            if str(record["provider_id"]) == memory_id:
                return self._to_domain_memory(record)
        return None

    def _to_provider_record(self, memory: StudentMemory) -> dict[str, Any]:
        provider_id = memory.memory_id or f"fake-mem-{uuid4().hex[:10]}"
        return {
            "provider_id": provider_id,
            "mem0_internal_id": f"mem0-fixture-{provider_id}",
            "user_id": memory.student_id,
            "memory": memory.content,
            "metadata": {
                "memory_type": memory.memory_type,
                "evidence": dict(memory.evidence),
                "provenance": dict(memory.provenance),
                "summary": memory.summary,
                "enabled": memory.enabled,
                "status": memory.status,
                "created_at": memory.created_at,
                "updated_at": memory.updated_at,
            },
            "sdk_response": {
                "object": "mem0.memory",
                "version": "fake-fixture/v1",
                "raw_provider_payload": {
                    "memory": memory.content,
                    "user_id": memory.student_id,
                    "metadata": dict(memory.evidence),
                },
            },
            "provider_debug": {
                "network": "disabled",
                "fixture": True,
            },
        }

    def _to_domain_memory(self, record: dict[str, Any]) -> StudentMemory:
        metadata = record.get("metadata", {})
        updated_at = str(metadata.get("updated_at") or datetime.now(UTC).isoformat())
        provenance = dict(metadata.get("provenance") or {})
        provenance["provider"] = {
            "name": "fake_mem0_fixture",
            "record_id": str(record["provider_id"]),
        }
        return StudentMemory(
            memory_id=str(record["provider_id"]),
            student_id=str(record["user_id"]),
            memory_type=metadata.get("memory_type", "reflection"),
            content=str(record["memory"]),
            summary=metadata.get("summary"),
            evidence=dict(metadata.get("evidence") or {}),
            relevance_score=_normalized_score(record.get("score")),
            freshness=memory_freshness(updated_at),
            source="fake_provider",
            provenance=provenance,
            enabled=bool(metadata.get("enabled", True)),
            status=_memory_status(metadata.get("status")),
            created_at=str(metadata.get("created_at") or datetime.now(UTC).isoformat()),
            updated_at=updated_at,
        )

    def _score(self, record: dict[str, Any], terms: set[str]) -> float:
        if not terms:
            return 0.1
        metadata = record.get("metadata", {})
        haystack = self._terms(
            " ".join(
                [
                    str(metadata.get("memory_type", "")),
                    str(record.get("memory", "")),
                    " ".join(map(str, (metadata.get("evidence") or {}).values())),
                ]
            )
        )
        return float(len(terms & haystack))

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
        terms = {term for term in normalized.split() if term}
        for keyword in ("偏好", "错因", "策略", "反思", "步骤", "比例", "方程", "分数", "通分", "公分母"):
            if keyword in normalized:
                terms.add(keyword)
        return terms


def _normalized_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(min(max(float(value), 0.0), 1.0), 4)
    except (TypeError, ValueError):
        return None


def _memory_status(value: Any) -> MemoryStatus:
    return value if value in {"enabled", "disabled"} else "enabled"
