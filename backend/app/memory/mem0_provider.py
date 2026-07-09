from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..provider_gaps import provider_evidence_gap, provider_exception_gap
from .store import (
    MemoryProviderConfigurationError,
    MemoryStatus,
    MemoryType,
    StudentMemory,
    apply_memory_control,
    memory_dedupe_key,
    memory_freshness,
)


RAW_PROVIDER_KEYS = {
    "raw_provider_payload",
    "sdk_response",
    "mem0_internal_id",
    "embedding_vector",
    "provider_debug",
    "vector",
    "embedding",
}


class MemoryProviderSchemaError(RuntimeError):
    pass


class Mem0StudentMemoryStore:
    """Mem0-backed StudentMemoryStore adapter.

    The adapter deliberately accepts and returns MathTutor domain models. Provider SDK
    payloads are normalized at this boundary and never exposed downstream.
    """

    provider_mode = "live_provider"
    source = "mem0"

    def __init__(
        self,
        *,
        api_key: str,
        client: Any | None = None,
        fallback_on_error: bool = True,
    ) -> None:
        if not api_key and client is None:
            raise MemoryProviderConfigurationError(
                "Mem0 live provider 需要 MATHTUTOR_MEM0_API_KEY；"
                "默认 local_fallback 不需要任何 Mem0 配置。"
            )
        self.client = client or self._build_client(api_key=api_key)
        self.fallback_on_error = fallback_on_error
        self.last_error: dict[str, Any] | None = None
        self.last_evidence_gaps: list[dict[str, Any]] = []

    def search(
        self,
        student_id: str,
        query: str,
        memory_types: list[MemoryType] | None = None,
        limit: int = 5,
    ) -> list[StudentMemory]:
        self._clear_provider_gaps()
        try:
            records = self._provider_search(
                student_id=student_id,
                query=query,
                memory_types=memory_types,
                limit=max(limit * 4, limit, 10),
            )
        except Exception as exc:
            if not self.fallback_on_error:
                raise
            self._record_error("search", exc)
            return []

        extracted_records = self._extract_records(records)
        if not extracted_records:
            self._record_gap(
                provider_evidence_gap(
                    gap_type="provider_empty_result",
                    provider="mem0",
                    operation="search",
                    reason="Mem0 search returned no memory records.",
                )
            )
            return []

        memories: list[StudentMemory] = []
        for index, record in enumerate(extracted_records):
            try:
                memories.append(self._to_domain_memory(record, student_id=student_id))
            except MemoryProviderSchemaError as exc:
                self._record_gap(
                    provider_evidence_gap(
                        gap_type="provider_schema_mismatch",
                        provider="mem0",
                        operation="search",
                        reason=str(exc),
                        details={"record_index": index},
                    )
                )
        if memory_types:
            allowed = set(memory_types)
            memories = [memory for memory in memories if memory.memory_type in allowed]
        memories = [
            memory for memory in memories if memory.enabled and memory.status == "enabled"
        ]
        if not memories and not self._has_gap("provider_schema_mismatch"):
            self._record_gap(
                provider_evidence_gap(
                    gap_type="provider_empty_result",
                    provider="mem0",
                    operation="search",
                    reason="Mem0 search returned no matching normalized memories.",
                    details={"memory_types": list(memory_types or [])},
                )
            )
        memories.sort(
            key=lambda memory: (
                -(memory.relevance_score or 0.0),
                _newest_first_sort_value(memory.updated_at),
                memory.memory_id,
            )
        )
        return memories[:limit]

    def write(self, memory: StudentMemory) -> StudentMemory:
        self._clear_provider_gaps()
        prepared = self._prepare_memory(memory)
        try:
            existing = self._find_existing(prepared)
            if existing is not None:
                merged = self._merge_memories(existing, prepared)
                updated = self._provider_update(merged)
                if updated is None:
                    return merged
                return self._to_domain_memory(updated, fallback=merged, student_id=memory.student_id)

            added = self._provider_add(prepared)
            return self._to_domain_memory(added, fallback=prepared, student_id=memory.student_id)
        except Exception as exc:
            if not self.fallback_on_error:
                raise
            gap = self._record_error("write", exc)
            return prepared.model_copy(
                update={
                    "source": "mem0_unavailable",
                    "provenance": prepared.provenance
                    | {
                        "provider_failure": {
                            "operation": "write",
                            "provider": "mem0",
                            "gap_type": gap["gap_type"],
                            "reason": gap["reason"],
                        }
                    },
                }
            )

    def list_recent(self, student_id: str, limit: int = 10) -> list[StudentMemory]:
        self._clear_provider_gaps()
        try:
            records = self._provider_get_all(student_id=student_id, limit=max(limit * 4, 20))
        except Exception as exc:
            if not self.fallback_on_error:
                raise
            self._record_error("list_recent", exc)
            return []

        memories: list[StudentMemory] = []
        for index, record in enumerate(self._extract_records(records)):
            try:
                memories.append(self._to_domain_memory(record, student_id=student_id))
            except MemoryProviderSchemaError as exc:
                self._record_gap(
                    provider_evidence_gap(
                        gap_type="provider_schema_mismatch",
                        provider="mem0",
                        operation="list_recent",
                        reason=str(exc),
                        details={"record_index": index},
                    )
                )
        memories = [memory for memory in memories if memory.student_id == student_id]
        memories.sort(
            key=lambda memory: (_newest_first_sort_value(memory.updated_at), memory.memory_id)
        )
        return memories[:limit]

    def get(self, student_id: str, memory_id: str) -> StudentMemory | None:
        self._clear_provider_gaps()
        try:
            records = self._provider_get_all(student_id=student_id, limit=100)
        except Exception as exc:
            if not self.fallback_on_error:
                raise
            self._record_error("get", exc)
            return None

        for index, record in enumerate(self._extract_records(records)):
            try:
                memory = self._to_domain_memory(record, student_id=student_id)
            except MemoryProviderSchemaError as exc:
                self._record_gap(
                    provider_evidence_gap(
                        gap_type="provider_schema_mismatch",
                        provider="mem0",
                        operation="get",
                        reason=str(exc),
                        details={"record_index": index},
                    )
                )
                continue
            if memory.student_id == student_id and memory.memory_id == memory_id:
                return memory
        return None

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

    def _set_enabled(
        self,
        *,
        student_id: str,
        memory_id: str,
        enabled: bool,
        actor: str,
        reason: str | None,
    ) -> StudentMemory | None:
        memory = self.get(student_id=student_id, memory_id=memory_id)
        if memory is None:
            return None
        controlled = apply_memory_control(
            memory,
            enabled=enabled,
            actor=actor,
            reason=reason,
        )
        self._clear_provider_gaps()
        try:
            updated = self._provider_update(controlled)
            if updated is None:
                return controlled
            return self._to_domain_memory(updated, fallback=controlled, student_id=student_id)
        except Exception as exc:
            if not self.fallback_on_error:
                raise
            gap = self._record_error("memory_control", exc)
            return controlled.model_copy(
                update={
                    "source": "mem0_unavailable",
                    "provenance": controlled.provenance
                    | {
                        "provider_failure": {
                            "operation": "memory_control",
                            "provider": "mem0",
                            "gap_type": gap["gap_type"],
                            "reason": gap["reason"],
                        }
                    },
                }
            )

    def _build_client(self, *, api_key: str) -> Any:
        try:
            from mem0 import MemoryClient  # type: ignore[import-not-found]
        except ImportError as exc:
            raise MemoryProviderConfigurationError(
                "已选择 Mem0 live provider，但当前环境未安装 Mem0 SDK。"
                "请安装可选依赖 mem0ai，或切回 MATHTUTOR_MEMORY_PROVIDER_MODE=local_fallback。"
            ) from exc
        return MemoryClient(api_key=api_key)

    def _provider_search(
        self,
        *,
        student_id: str,
        query: str,
        memory_types: list[MemoryType] | None,
        limit: int,
    ) -> Any:
        filters = self._provider_filters(memory_types)
        attempts = [
            lambda: self.client.search(
                query=query,
                user_id=student_id,
                limit=limit,
                filters=filters,
            ),
            lambda: self.client.search(query=query, user_id=student_id, limit=limit),
            lambda: self.client.search(query, user_id=student_id, limit=limit),
        ]
        return _first_success(attempts)

    def _provider_add(self, memory: StudentMemory) -> Any:
        metadata = self._metadata_for(memory)
        message = [{"role": "user", "content": memory.content}]
        attempts = [
            lambda: self.client.add(memory.content, user_id=memory.student_id, metadata=metadata),
            lambda: self.client.add(message, user_id=memory.student_id, metadata=metadata),
            lambda: self.client.add(messages=message, user_id=memory.student_id, metadata=metadata),
        ]
        return _first_success(attempts)

    def _provider_get_all(self, *, student_id: str, limit: int) -> Any:
        attempts = [
            lambda: self.client.get_all(user_id=student_id, limit=limit),
            lambda: self.client.get_all(user_id=student_id),
            lambda: self.client.get_all(student_id),
        ]
        return _first_success(attempts)

    def _provider_update(self, memory: StudentMemory) -> Any | None:
        metadata = self._metadata_for(memory)
        payload = {"memory": memory.content, "text": memory.content, "metadata": metadata}
        attempts = [
            lambda: self.client.update(memory_id=memory.memory_id, data=payload),
            lambda: self.client.update(memory.memory_id, data=payload),
            lambda: self.client.update(
                memory_id=memory.memory_id,
                memory=memory.content,
                metadata=metadata,
            ),
            lambda: self.client.update(memory.memory_id, memory=memory.content, metadata=metadata),
        ]
        try:
            return _first_success(attempts)
        except (AttributeError, TypeError, RuntimeError):
            return None

    def _provider_filters(self, memory_types: list[MemoryType] | None) -> dict[str, Any]:
        if not memory_types:
            return {}
        if len(memory_types) == 1:
            return {"metadata": {"memory_type": memory_types[0]}}
        return {"metadata": {"memory_type": {"$in": list(memory_types)}}}

    def _prepare_memory(self, memory: StudentMemory) -> StudentMemory:
        now = datetime.now(UTC).isoformat()
        updated_at = memory.updated_at or now
        provenance = _sanitize_dict(memory.provenance)
        if memory.evidence.get("source_event") and not provenance.get("source_event"):
            provenance["source_event"] = memory.evidence["source_event"]
        if memory.evidence.get("trace_id") and not provenance.get("trace_id"):
            provenance["trace_id"] = memory.evidence["trace_id"]
        if memory.evidence.get("event_time") and not provenance.get("occurred_at"):
            provenance["occurred_at"] = memory.evidence["event_time"]
        provenance["dedupe_key"] = memory_dedupe_key(memory)
        return memory.model_copy(
            update={
                "source": self.source,
                "freshness": memory_freshness(updated_at),
                "provenance": provenance,
                "updated_at": updated_at,
            }
        )

    def _metadata_for(self, memory: StudentMemory) -> dict[str, Any]:
        return {
            "schema": "mathtutor.student_memory.v1",
            "memory_id": memory.memory_id,
            "student_id": memory.student_id,
            "memory_type": memory.memory_type,
            "evidence": _sanitize_dict(memory.evidence),
            "provenance": _sanitize_dict(memory.provenance),
            "summary": memory.summary,
            "enabled": memory.enabled,
            "status": memory.status,
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
            "dedupe_key": memory_dedupe_key(memory),
            "source": self.source,
        }

    def _find_existing(self, memory: StudentMemory) -> StudentMemory | None:
        dedupe_key = memory.provenance.get("dedupe_key") or memory_dedupe_key(memory)
        candidates = self.list_recent(memory.student_id, limit=100)
        if not candidates:
            candidates = self.search(
                student_id=memory.student_id,
                query=memory.content,
                memory_types=[memory.memory_type],
                limit=20,
            )
        for candidate in candidates:
            candidate_key = candidate.provenance.get("dedupe_key") or memory_dedupe_key(candidate)
            if candidate_key == dedupe_key:
                return candidate
        return None

    def _merge_memories(self, existing: StudentMemory, incoming: StudentMemory) -> StudentMemory:
        now = datetime.now(UTC).isoformat()
        provenance = {**existing.provenance, **incoming.provenance}
        provider = existing.provenance.get("provider") or incoming.provenance.get("provider")
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
        session_ids = _unique_values(
            existing.provenance.get("session_ids"),
            existing.provenance.get("session_id"),
            incoming.provenance.get("session_ids"),
            incoming.provenance.get("session_id"),
        )
        event_times = _unique_values(
            existing.provenance.get("event_times"),
            existing.provenance.get("occurred_at"),
            incoming.provenance.get("event_times"),
            incoming.provenance.get("occurred_at"),
            existing.evidence.get("event_time"),
            incoming.evidence.get("event_time"),
        )
        if provider:
            provenance["provider"] = provider
        if trace_ids:
            provenance["trace_ids"] = trace_ids
        if event_sources:
            provenance["event_sources"] = event_sources
        if session_ids:
            provenance["session_ids"] = session_ids
        if event_times:
            provenance["event_times"] = event_times
        provenance["dedupe_key"] = memory_dedupe_key(incoming)
        return existing.model_copy(
            update={
                "content": incoming.content,
                "evidence": {**existing.evidence, **incoming.evidence},
                "provenance": provenance,
                "updated_at": now,
                "freshness": "fresh",
                "source": self.source,
            }
        )

    def _to_domain_memory(
        self,
        record: Any,
        *,
        student_id: str,
        fallback: StudentMemory | None = None,
    ) -> StudentMemory:
        if isinstance(record, StudentMemory):
            return record.model_copy(update={"source": self.source})
        if not isinstance(record, dict):
            record = {"memory": str(record), "metadata": {}}

        metadata = _sanitize_dict(_as_dict(record.get("metadata")))
        fallback = fallback or StudentMemory(
            student_id=student_id,
            memory_type="reflection",
            content=str(record.get("memory") or record.get("text") or record.get("content") or ""),
        )
        memory_id = str(
            record.get("id")
            or record.get("memory_id")
            or record.get("provider_id")
            or metadata.get("memory_id")
            or fallback.memory_id
        )
        created_at = str(
            metadata.get("created_at")
            or record.get("created_at")
            or fallback.created_at
            or datetime.now(UTC).isoformat()
        )
        updated_at = str(
            metadata.get("updated_at")
            or record.get("updated_at")
            or fallback.updated_at
            or created_at
        )
        memory_type = _memory_type(metadata.get("memory_type") or fallback.memory_type)
        evidence = _sanitize_dict(metadata.get("evidence") or fallback.evidence)
        provenance = _sanitize_dict(metadata.get("provenance") or fallback.provenance)
        enabled = _enabled(metadata.get("enabled"), fallback=fallback.enabled)
        status = _memory_status(metadata.get("status"), enabled=enabled)
        provenance["provider"] = {
            "name": "mem0",
            "record_id": memory_id,
        }
        provenance["dedupe_key"] = metadata.get("dedupe_key") or memory_dedupe_key(
            fallback.model_copy(update={"evidence": evidence, "memory_type": memory_type})
        )
        content = str(
            record.get("memory")
            or record.get("text")
            or record.get("content")
            or fallback.content
        )
        if not content:
            raise MemoryProviderSchemaError("Mem0 provider result missing memory content.")
        return StudentMemory(
            memory_id=memory_id,
            student_id=str(record.get("user_id") or metadata.get("student_id") or student_id),
            memory_type=memory_type,
            content=content,
            summary=str(metadata.get("summary")) if metadata.get("summary") else fallback.summary,
            evidence=evidence,
            relevance_score=_relevance_score(record, fallback=fallback.relevance_score),
            freshness=memory_freshness(updated_at),
            source=self.source,
            provenance=provenance,
            enabled=enabled,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _extract_records(self, response: Any) -> list[Any]:
        if response is None:
            return []
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            for key in ("results", "memories", "data"):
                value = response.get(key)
                if isinstance(value, list):
                    return value
            return [response]
        return [response]

    def _record_error(self, operation: str, exc: Exception) -> dict[str, Any]:
        gap = provider_exception_gap(provider="mem0", operation=operation, exc=exc)
        self.last_error = gap
        self._record_gap(gap)
        return gap

    def _record_gap(self, gap: dict[str, Any]) -> None:
        key = (gap.get("gap_type"), gap.get("operation"), gap.get("reason"))
        existing = {
            (item.get("gap_type"), item.get("operation"), item.get("reason"))
            for item in self.last_evidence_gaps
        }
        if key not in existing:
            self.last_evidence_gaps.append(gap)

    def _clear_provider_gaps(self) -> None:
        self.last_error = None
        self.last_evidence_gaps = []

    def _has_gap(self, gap_type: str) -> bool:
        return any(gap.get("gap_type") == gap_type for gap in self.last_evidence_gaps)


def _first_success(attempts: list[Any]) -> Any:
    last_error: Exception | None = None
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            last_error = exc
            continue
        except AttributeError as exc:
            last_error = exc
            continue
    raise RuntimeError(str(last_error) if last_error else "provider call failed")


def _sanitize_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        if key in RAW_PROVIDER_KEYS:
            continue
        sanitized[str(key)] = _sanitize_value(item)
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _sanitize_dict(value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _memory_type(value: Any) -> MemoryType:
    if value in {"preference", "repeated_mistake", "effective_strategy", "reflection"}:
        return value
    return "reflection"


def _enabled(value: Any, *, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() not in {"false", "0", "disabled"}
    return fallback


def _memory_status(value: Any, *, enabled: bool) -> MemoryStatus:
    if value in {"enabled", "disabled"}:
        return value
    return "enabled" if enabled else "disabled"


def _relevance_score(record: dict[str, Any], *, fallback: float | None) -> float | None:
    for key in ("score", "relevance", "relevance_score"):
        value = record.get(key)
        if value is None:
            continue
        try:
            return round(min(max(float(value), 0.0), 1.0), 4)
        except (TypeError, ValueError):
            continue
    return fallback


def _newest_first_sort_value(value: str) -> float:
    try:
        return -datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def _unique_values(*values: Any) -> list[str]:
    items: list[str] = []
    for value in values:
        if value is None:
            continue
        candidates = value if isinstance(value, (list, tuple, set)) else [value]
        for candidate in candidates:
            text = str(candidate)
            if text and text not in items:
                items.append(text)
    return items
