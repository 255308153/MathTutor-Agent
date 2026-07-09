from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.main import create_app
from backend.app.memory.fake_provider import FakeStudentMemoryProvider
from backend.app.memory.store import InMemoryStudentMemoryStore, StudentMemory, StudentMemoryStore


@pytest.mark.parametrize(
    ("provider_name", "store_factory"),
    [
        ("local_fallback", InMemoryStudentMemoryStore),
        ("fake_provider", FakeStudentMemoryProvider),
    ],
)
def test_student_memory_read_api_lists_and_details_without_provider_payload_leaks(
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
    store_factory: Callable[[], StudentMemoryStore],
) -> None:
    store = store_factory()
    student_id = f"student-memory-control-{provider_name}"
    memory = store.write(
        StudentMemory(
            student_id=student_id,
            memory_type="preference",
            content="学生偏好先看分数通分的步骤化讲解。",
            summary="偏好步骤化分数讲解",
            evidence={
                "preferred_concept_id": "c_fraction_addition",
                "raw_provider_payload": {"private": True},
                "embedding_vector": [0.1, 0.2, 0.3],
            },
            provenance={
                "source_event": "event:trace-memory-control:answer_submitted",
                "trace_id": "trace-memory-control",
                "provider_debug": {"request_id": "hidden"},
                "sdk_response": {"object": "mem0.memory"},
            },
        )
    )
    monkeypatch.setattr(events_api, "learning_loop", SimpleNamespace(memories=store))
    client = TestClient(create_app())

    response = client.get(f"/api/students/{student_id}/memories")

    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert body["count"] == 1
    item = body["memories"][0]
    assert item["memory_id"] == memory.memory_id
    assert item["memory_type"] == "preference"
    assert item["content"] == "学生偏好先看分数通分的步骤化讲解。"
    assert item["summary"] == "偏好步骤化分数讲解"
    assert item["source"] in {"local_fallback", "fake_provider"}
    assert item["evidence"] == {"preferred_concept_id": "c_fraction_addition"}
    assert item["provenance"]["source_event"] == "event:trace-memory-control:answer_submitted"
    assert item["provenance"]["trace_id"] == "trace-memory-control"
    assert item["freshness"] in {"fresh", "recent", "stale"}
    assert item["enabled"] is True
    assert item["status"] == "enabled"
    assert item["created_at"]
    assert item["updated_at"]

    detail = client.get(f"/api/students/{student_id}/memories/{memory.memory_id}")

    assert detail.status_code == 200
    assert detail.json()["memory"] == item
    serialized = json.dumps(body | detail.json(), ensure_ascii=False)
    for raw_provider_key in (
        "raw_provider_payload",
        "sdk_response",
        "mem0_internal_id",
        "embedding_vector",
        "provider_debug",
        "api_key",
        "secret",
    ):
        assert raw_provider_key not in serialized


def test_student_memory_detail_api_returns_404_for_missing_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStudentMemoryStore()
    monkeypatch.setattr(events_api, "learning_loop", SimpleNamespace(memories=store))
    client = TestClient(create_app())

    response = client.get("/api/students/student-missing/memories/mem-missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "学生记忆不存在"
