from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.context.learning_context import InMemoryContextAssetStore, LearningContextLayer
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.main import create_app
from backend.app.memory.mem0_provider import Mem0StudentMemoryStore
from backend.app.memory.store import StudentMemory
from backend.app.provider_gaps import (
    PROVIDER_EVIDENCE_GAP_TYPES,
    provider_exception_gap,
)
from backend.app.rag.viking_provider import VikingKnowledgeRAGAdapter
from backend.app.storage.progress_store import InMemoryProgressStore


class RaisingMem0Client:
    def __init__(self, *, search_exc: Exception) -> None:
        self.search_exc = search_exc

    def search(self, *_: Any, **__: Any) -> Any:
        raise self.search_exc

    def get_all(self, *_: Any, **__: Any) -> list[Any]:
        return []

    def add(self, *_: Any, **__: Any) -> Any:
        raise self.search_exc


class EmptyMem0Client:
    def search(self, *_: Any, **__: Any) -> list[Any]:
        return []


class MalformedMem0Client:
    def search(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        return [{"id": "mem0-malformed", "metadata": {"memory_type": "preference"}}]


class RaisingRAGClient:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def search(self, **_: Any) -> Any:
        raise self.exc


class EmptyRAGClient:
    def search(self, **_: Any) -> list[Any]:
        return []


class MalformedRAGClient:
    def search(self, **_: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "rag-malformed",
                "metadata": {
                    "doc_type": "question_explanation",
                    "title": "malformed provider record",
                },
            }
        ]


class EmptyRAG:
    allows_question_to_concept_fallback = False

    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> list[Any]:
        del query, filters, limit
        return []


@pytest.mark.parametrize(
    ("exc", "gap_type"),
    [
        (TimeoutError("provider timed out"), "provider_timeout"),
        (PermissionError("401 unauthorized api key"), "provider_auth_error"),
        (RuntimeError("provider crashed"), "provider_failure"),
        (RuntimeError("provider budget exceeded"), "provider_budget_exceeded"),
    ],
)
def test_mem0_search_failures_become_structured_provider_gaps(
    exc: Exception,
    gap_type: str,
) -> None:
    store = Mem0StudentMemoryStore(
        client=RaisingMem0Client(search_exc=exc),
        api_key="test-key",
    )

    assert store.search("student-provider-gap", "通分", limit=3) == []

    assert [gap["gap_type"] for gap in store.last_evidence_gaps] == [gap_type]
    gap = store.last_evidence_gaps[0]
    assert gap["provider"] == "mem0"
    assert gap["operation"] == "search"
    assert gap["gap_type"] in PROVIDER_EVIDENCE_GAP_TYPES
    assert gap["details"]["exception_type"] == exc.__class__.__name__


@pytest.mark.parametrize(
    ("client", "gap_type"),
    [
        (EmptyMem0Client(), "provider_empty_result"),
        (MalformedMem0Client(), "provider_schema_mismatch"),
    ],
)
def test_mem0_empty_and_malformed_results_do_not_fabricate_memory(
    client: Any,
    gap_type: str,
) -> None:
    store = Mem0StudentMemoryStore(client=client, api_key="test-key")

    assert store.search("student-provider-gap", "通分", limit=3) == []

    assert any(gap["gap_type"] == gap_type for gap in store.last_evidence_gaps)


def test_provider_gap_sanitizes_raw_payload_and_exception_secrets() -> None:
    gap = provider_exception_gap(
        provider="mem0",
        operation="search",
        exc=RuntimeError(
            "Authorization: Bearer live-secret X-Api-Key: also-secret api_key=third-secret"
        ),
        details={
            "raw_provider_payload": {"token": "raw-secret"},
            "safe_nested": {"embedding": [0.1, 0.2], "kept": "visible"},
        },
    )

    serialized = str(gap)
    assert "live-secret" not in serialized
    assert "also-secret" not in serialized
    assert "third-secret" not in serialized
    assert "raw-secret" not in serialized
    assert "raw_provider_payload" not in gap["details"]
    assert "embedding" not in gap["details"]["safe_nested"]
    assert gap["details"]["safe_nested"]["kept"] == "visible"


def test_mem0_write_fallback_uses_sanitized_gap_reason() -> None:
    store = Mem0StudentMemoryStore(
        client=RaisingMem0Client(
            search_exc=RuntimeError("Authorization: Bearer write-secret")
        ),
        api_key="test-key",
    )

    written = store.write(
        StudentMemory(
            student_id="student-provider-gap",
            memory_type="preference",
            content="喜欢先看图形解释",
        )
    )

    assert written.source == "mem0_unavailable"
    serialized = str(written.model_dump())
    assert "write-secret" not in serialized
    assert written.provenance["provider_failure"]["gap_type"] == "provider_auth_error"
    assert "reason" in written.provenance["provider_failure"]


@pytest.mark.parametrize(
    ("exc", "gap_type"),
    [
        (TimeoutError("provider timed out"), "provider_timeout"),
        (PermissionError("403 forbidden"), "provider_auth_error"),
        (RuntimeError("provider crashed"), "provider_failure"),
        (RuntimeError("provider budget exceeded"), "provider_budget_exceeded"),
    ],
)
def test_viking_search_failures_become_structured_provider_gaps(
    exc: Exception,
    gap_type: str,
) -> None:
    rag = _viking_adapter(RaisingRAGClient(exc), fallback=EmptyRAG())

    assert rag.search("通分", filters={"concept_id": "c_fraction_addition"}, limit=3) == []

    assert [gap["gap_type"] for gap in rag.last_evidence_gaps] == [gap_type]
    gap = rag.last_evidence_gaps[0]
    assert gap["provider"] == "openviking"
    assert gap["operation"] == "search"
    assert gap["gap_type"] in PROVIDER_EVIDENCE_GAP_TYPES


@pytest.mark.parametrize(
    ("client", "gap_type"),
    [
        (EmptyRAGClient(), "provider_empty_result"),
        (MalformedRAGClient(), "provider_schema_mismatch"),
    ],
)
def test_viking_empty_and_malformed_results_do_not_fabricate_citations(
    client: Any,
    gap_type: str,
) -> None:
    rag = _viking_adapter(client)

    assert rag.search("通分", filters={"concept_id": "c_fraction_addition"}, limit=3) == []

    assert any(gap["gap_type"] == gap_type for gap in rag.last_evidence_gaps)


def test_learning_event_continues_and_records_provider_gaps_without_fabricating_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memories = Mem0StudentMemoryStore(
        client=RaisingMem0Client(search_exc=TimeoutError("provider timed out")),
        api_key="test-key",
    )
    rag = _viking_adapter(MalformedRAGClient())
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=memories,
        rag=rag,
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-provider-gap-flow",
            "student_id": "student-provider-gap-flow",
            "type": "answer_submitted",
            "message": "我选 1/6，验证 provider 降级。",
            "payload": {"question_id": "q_frac_001", "answer": "1/6"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    gaps = expert["assembled_context"]["evidence_gaps"]

    assert "判定为不正确" in body["response"]
    assert expert["student_memories"] == []
    assert expert["rag_sources"] == []
    assert not [
        asset
        for asset in expert["context_assets"]
        if asset["asset_type"] in {"student_memory", "knowledge_resource"}
    ]
    assert {"provider_timeout", "provider_schema_mismatch"} <= {
        gap["gap_type"] for gap in gaps
    }
    assert any(record["category"] == "provider_timeout" for record in expert["error_records"])
    assert any(
        record["category"] == "provider_schema_mismatch"
        for record in expert["error_records"]
    )
    assert expert["assembled_context"]["authoritative_kt_facts"]["prediction_probability"] == (
        expert["kt_diagnosis"]["prediction_probability"]
    )
    load_context = next(
        event for event in body["teaching_trace"] if event["stage"] == "load_context"
    )
    assert any(
        record["category"] == "provider_timeout"
        for record in load_context["metadata"]["evidence_gap_records"]
    )


def test_default_local_fallback_has_no_provider_gap_types() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-provider-gap-default",
            "student_id": "student-provider-gap-default",
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    gaps = response.json()["teaching_trace_summary"]["expert_evidence"][
        "assembled_context"
    ]["evidence_gaps"]
    assert not {gap["gap_type"] for gap in gaps} & PROVIDER_EVIDENCE_GAP_TYPES


def _viking_adapter(
    client: Any,
    *,
    fallback: Any | None = None,
) -> VikingKnowledgeRAGAdapter:
    return VikingKnowledgeRAGAdapter(
        provider_name="openviking",
        provider_mode="live_provider",
        collection="assist2017-smoke",
        client=client,
        fallback=fallback,
    )
