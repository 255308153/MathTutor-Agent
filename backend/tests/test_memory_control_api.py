from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.context.learning_context import InMemoryContextAssetStore, LearningContextLayer
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.main import create_app
from backend.app.memory.fake_provider import FakeStudentMemoryProvider
from backend.app.memory.mem0_provider import Mem0StudentMemoryStore
from backend.app.memory.store import InMemoryStudentMemoryStore, StudentMemory, StudentMemoryStore
from backend.app.storage.progress_store import InMemoryProgressStore


class FailingMem0ControlClient:
    def __init__(
        self,
        *,
        record: dict[str, Any] | None = None,
        get_all_exc: Exception | None = None,
        update_exc: Exception | None = None,
        delete_exc: Exception | None = None,
    ) -> None:
        self.records = [record or _mem0_memory_record()]
        self.get_all_exc = get_all_exc
        self.update_exc = update_exc
        self.delete_exc = delete_exc

    def get_all(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        if self.get_all_exc:
            raise self.get_all_exc
        return list(self.records)

    def search(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        return list(self.records)

    def update(self, *_: Any, **__: Any) -> dict[str, Any]:
        if self.update_exc:
            raise self.update_exc
        return self.records[0]

    def delete(self, *_: Any, **__: Any) -> None:
        if self.delete_exc:
            raise self.delete_exc
        self.records.clear()


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


@pytest.mark.parametrize(
    ("provider_name", "store_factory"),
    [
        ("local_fallback", InMemoryStudentMemoryStore),
        ("fake_provider", FakeStudentMemoryProvider),
    ],
)
def test_student_memory_control_api_disables_and_reenables_memory(
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
    store_factory: Callable[[], StudentMemoryStore],
) -> None:
    store = store_factory()
    student_id = f"student-memory-toggle-{provider_name}"
    memory = store.write(
        StudentMemory(
            student_id=student_id,
            memory_type="preference",
            content="学生偏好先看比例题的步骤化讲解。",
            evidence={"preferred_concept_id": "c_ratio"},
        )
    )
    monkeypatch.setattr(events_api, "learning_loop", SimpleNamespace(memories=store))
    client = TestClient(create_app())

    disabled_response = client.post(
        f"/api/students/{student_id}/memories/{memory.memory_id}/disable",
        json={"actor": "student", "reason": "暂时不要让这条记忆影响推荐。"},
    )

    assert disabled_response.status_code == 200
    disabled = disabled_response.json()["memory"]
    assert disabled["enabled"] is False
    assert disabled["status"] == "disabled"
    assert disabled["provenance"]["control"]["operation"] == "disable"
    assert disabled["provenance"]["control"]["reason"] == "暂时不要让这条记忆影响推荐。"
    assert store.search(student_id=student_id, query="比例 步骤", limit=5) == []

    listed = client.get(f"/api/students/{student_id}/memories").json()["memories"]
    assert listed[0]["memory_id"] == memory.memory_id
    assert listed[0]["status"] == "disabled"

    enabled_response = client.post(
        f"/api/students/{student_id}/memories/{memory.memory_id}/enable",
        json={"actor": "student", "reason": "重新允许这条记忆参与推荐。"},
    )

    assert enabled_response.status_code == 200
    enabled = enabled_response.json()["memory"]
    assert enabled["enabled"] is True
    assert enabled["status"] == "enabled"
    assert enabled["provenance"]["control"]["operation"] == "enable"
    assert store.search(student_id=student_id, query="比例 步骤", limit=5)[0].memory_id == (
        memory.memory_id
    )


@pytest.mark.parametrize(
    ("provider_name", "store_factory"),
    [
        ("local_fallback", InMemoryStudentMemoryStore),
        ("fake_provider", FakeStudentMemoryProvider),
    ],
)
def test_student_memory_delete_api_removes_memory_from_ordinary_results(
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
    store_factory: Callable[[], StudentMemoryStore],
) -> None:
    store = store_factory()
    student_id = f"student-memory-delete-{provider_name}"
    memory = store.write(
        StudentMemory(
            student_id=student_id,
            memory_type="preference",
            content="学生偏好先看比例题的步骤化讲解。",
            evidence={"preferred_concept_id": "c_ratio"},
        )
    )
    monkeypatch.setattr(events_api, "learning_loop", SimpleNamespace(memories=store))
    client = TestClient(create_app())

    deleted_response = client.request(
        "DELETE",
        f"/api/students/{student_id}/memories/{memory.memory_id}",
        json={"actor": "student", "reason": "这条记忆已经不想保留。"},
    )

    assert deleted_response.status_code == 200
    deleted = deleted_response.json()["memory"]
    assert deleted["enabled"] is False
    assert deleted["status"] == "deleted"
    assert deleted["provenance"]["control"]["operation"] == "delete"
    assert deleted["provenance"]["control"]["reason"] == "这条记忆已经不想保留。"
    assert client.get(f"/api/students/{student_id}/memories/{memory.memory_id}").status_code == 404
    assert client.get(f"/api/students/{student_id}/memories").json()["memories"] == []
    assert store.search(student_id=student_id, query="比例 步骤", limit=5) == []


@pytest.mark.parametrize(
    ("path_suffix", "operation"),
    [
        ("memories", "list_recent"),
        ("memories/mem0-control-memory", "get"),
    ],
)
def test_provider_view_failure_returns_structured_recoverable_error(
    monkeypatch: pytest.MonkeyPatch,
    path_suffix: str,
    operation: str,
) -> None:
    store = Mem0StudentMemoryStore(
        client=FailingMem0ControlClient(
            get_all_exc=TimeoutError("provider timed out api_key=hidden-secret")
        ),
        api_key="test-key",
    )
    monkeypatch.setattr(events_api, "learning_loop", SimpleNamespace(memories=store))
    client = TestClient(create_app())

    response = client.get(f"/api/students/student-mem0-control/{path_suffix}")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "provider_timeout"
    assert detail["category"] == "provider_timeout"
    assert detail["provider"] == "mem0"
    assert detail["operation"] == operation
    assert detail["recoverable"] is True
    assert "local flow continues" in detail["actionable_hint"]
    assert "hidden-secret" not in json.dumps(detail, ensure_ascii=False)


def test_provider_control_failure_is_structured_and_learning_flow_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Mem0StudentMemoryStore(
        client=FailingMem0ControlClient(
            update_exc=TimeoutError("provider timed out while updating control")
        ),
        api_key="test-key",
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=store,
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    control_response = client.post(
        "/api/students/student-mem0-control/memories/mem0-control-memory/disable",
        json={"actor": "student", "reason": "暂时禁用"},
    )

    assert control_response.status_code == 503
    detail = control_response.json()["detail"]
    assert detail["code"] == "provider_timeout"
    assert detail["provider"] == "mem0"
    assert detail["operation"] == "memory_control"
    assert detail["recoverable"] is True
    assert store.get(
        student_id="student-mem0-control",
        memory_id="mem0-control-memory",
    ).status == "enabled"

    event_response = client.post(
        "/api/events",
        json={
            "session_id": "session-control-provider-failure",
            "student_id": "student-mem0-control",
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {},
        },
    )
    assert event_response.status_code == 200
    body = event_response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assert "diagnose" in body["teaching_trace_summary"]["stages"]
    assert "context_assemble" in body["teaching_trace_summary"]["stages"]
    assert expert["kt_diagnosis"]["weak_concepts"] == body["state_summary"]["weak_concepts"]
    assert expert["assembled_context"]["authoritative_kt_facts"][
        "prediction_probability"
    ] == expert["kt_diagnosis"]["prediction_probability"]


def test_provider_delete_failure_is_structured_and_does_not_tombstone_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Mem0StudentMemoryStore(
        client=FailingMem0ControlClient(
            delete_exc=TimeoutError("provider timed out while deleting memory")
        ),
        api_key="test-key",
    )
    monkeypatch.setattr(events_api, "learning_loop", SimpleNamespace(memories=store))
    client = TestClient(create_app())

    delete_response = client.request(
        "DELETE",
        "/api/students/student-mem0-control/memories/mem0-control-memory",
        json={"actor": "student", "reason": "删除错误记忆"},
    )

    assert delete_response.status_code == 503
    detail = delete_response.json()["detail"]
    assert detail["code"] == "provider_timeout"
    assert detail["operation"] == "memory_delete"
    assert detail["recoverable"] is True
    assert store.get(
        student_id="student-mem0-control",
        memory_id="mem0-control-memory",
    ).status == "enabled"
    assert store.search(
        student_id="student-mem0-control",
        query="比例 步骤",
        limit=5,
    )[0].memory_id == "mem0-control-memory"


def test_student_memory_detail_api_returns_404_for_missing_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStudentMemoryStore()
    monkeypatch.setattr(events_api, "learning_loop", SimpleNamespace(memories=store))
    client = TestClient(create_app())

    response = client.get("/api/students/student-missing/memories/mem-missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "学生记忆不存在"


def _mem0_memory_record() -> dict[str, Any]:
    return {
        "id": "mem0-control-memory",
        "memory": "学生偏好比例题的步骤化讲解。",
        "user_id": "student-mem0-control",
        "metadata": {
            "memory_id": "mem0-control-memory",
            "student_id": "student-mem0-control",
            "memory_type": "preference",
            "evidence": {"preferred_concept_id": "c_ratio"},
            "provenance": {"source_event": "event:mem0-control"},
            "summary": "偏好比例题步骤讲解",
            "enabled": True,
            "status": "enabled",
            "created_at": "2026-07-09T08:00:00+00:00",
            "updated_at": "2026-07-09T08:00:00+00:00",
            "dedupe_key": "memory:mem0-control",
            "source": "mem0",
        },
        "score": 0.9,
    }
