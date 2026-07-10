from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.core.config import MathTutorSettings
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.main import create_app
from backend.app.memory.fake_provider import FakeStudentMemoryProvider
from backend.app.memory.store import (
    InMemoryStudentMemoryStore,
    MemoryProviderConfigurationError,
    StudentMemory,
    StudentMemoryStore,
    create_student_memory_store,
)
from backend.app.rag.fake_provider import FakeKnowledgeRAGProvider
from backend.app.rag.knowledge_rag import (
    LocalKnowledgeRAG,
    RAGProviderConfigurationError,
    create_knowledge_rag,
)
from backend.app.rag.schema import RAGSearchResult
from backend.app.rag.viking_provider import VikingKnowledgeRAGAdapter
from backend.app.storage.progress_store import InMemoryProgressStore


def test_default_provider_modes_keep_demo_mock_local_fallback() -> None:
    settings = MathTutorSettings()

    assert settings.memory_provider_mode == "local_fallback"
    assert settings.rag_provider_mode == "local_fallback"
    assert settings.run_mem0_live_smoke is False
    assert settings.run_viking_rag_smoke is False
    assert settings.viking_rag_smoke_query == ""
    assert settings.assist2017_dataset_mode == "demo"
    assert settings.content_source == "demo"
    assert settings.rag_source == "demo"
    assert settings.kt_engine == "mock"
    assert settings.mem0_api_key == ""
    assert settings.vikingdb_api_key == ""
    assert settings.openviking_api_key == ""
    # V1.11: local_fallback defaults to durable SQLite memory; in-memory is opt-in.
    from backend.app.memory.sqlite_store import SqliteStudentMemoryStore

    assert isinstance(create_student_memory_store(settings), SqliteStudentMemoryStore)
    memory_settings = settings.model_copy(update={"persistence_backend": "memory"})
    assert isinstance(create_student_memory_store(memory_settings), InMemoryStudentMemoryStore)
    assert isinstance(create_knowledge_rag(settings), LocalKnowledgeRAG)


@pytest.mark.parametrize(
    ("name", "store_factory"),
    [
        ("local_fallback", InMemoryStudentMemoryStore),
        ("fake_provider", FakeStudentMemoryProvider),
    ],
)
def test_student_memory_store_contract_is_shared_by_local_and_fake_provider(
    name: str,
    store_factory: Callable[[], StudentMemoryStore],
) -> None:
    assert name in {"local_fallback", "fake_provider"}
    _assert_student_memory_store_contract(store_factory())


@pytest.mark.parametrize(
    ("name", "rag_factory"),
    [
        ("local_fallback", LocalKnowledgeRAG),
        ("fake_provider", FakeKnowledgeRAGProvider),
    ],
)
def test_knowledge_rag_contract_is_shared_by_local_and_fake_provider(
    name: str,
    rag_factory: Callable[[], Any],
) -> None:
    assert name in {"local_fallback", "fake_provider"}
    _assert_knowledge_rag_contract(rag_factory())


def test_fake_provider_mode_runs_without_network_or_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for env_name in (
        "MATHTUTOR_MEM0_API_KEY",
        "MATHTUTOR_VIKINGDB_API_KEY",
        "MATHTUTOR_OPENVIKING_API_KEY",
    ):
        monkeypatch.delenv(env_name, raising=False)
    settings = MathTutorSettings(
        memory_provider_mode="fake_provider",
        rag_provider_mode="fake_provider",
        kt_engine="mock",
        assist2017_dataset_mode="demo",
        content_source="demo",
        rag_source="demo",
    )

    memories = create_student_memory_store(settings)
    rag = create_knowledge_rag(settings)

    assert isinstance(memories, FakeStudentMemoryProvider)
    assert isinstance(rag, FakeKnowledgeRAGProvider)
    _assert_student_memory_store_contract(memories)
    _assert_knowledge_rag_contract(rag)


def test_fake_viking_provider_contract_covers_filters_empty_and_normalization() -> None:
    rag = FakeKnowledgeRAGProvider()

    results = rag.search(
        query="通分 题解",
        filters={
            "question_id": "q_frac_001",
            "assistments2017_question_id": 3,
            "assistments2017_concept_id": "2",
        },
        limit=5,
    )

    assert {result.doc_id for result in results} == {
        "fake-rag-q-frac-001-solution",
        "fake-rag-fraction-mistake",
    }
    assert all(result.question_id == "q_frac_001" for result in results)
    assert all(result.assist2017_question_id == 3 for result in results)
    assert all(result.assist2017_concept_id == 2 for result in results)
    assert all(result.provenance["provider_mode"] == "fake_provider" for result in results)
    assert all(result.provenance["provider_name"] == "fake_vikingdb" for result in results)
    assert results[0].canonical_mapping["source"] == "fake_provider_fixture"
    assert results[0].coverage["concept_aligned"] is True

    assert rag.search(
        query="通分",
        filters={"concept_id": "c_provider_missing"},
        limit=3,
    ) == []

    serialized = json.dumps([result.model_dump() for result in results], ensure_ascii=False)
    for raw_provider_key in (
        "raw_provider_payload",
        "sdk_response",
        "vikingdb_distance",
        "embedding_vector",
        "provider_debug",
    ):
        assert raw_provider_key not in serialized


def test_fake_viking_provider_post_filters_when_provider_does_not_support_metadata_filter() -> None:
    rag = FakeKnowledgeRAGProvider(provider_supports_metadata_filter=False)

    results = rag.search(
        query="通分 策略",
        filters={
            "doc_type": "learning_strategy",
            "concept_id": "c_fraction_addition",
            "assist2017_concept_id": 2,
        },
        limit=5,
    )

    assert [result.doc_id for result in results] == ["fake-rag-fraction-strategy"]
    assert results[0].doc_type == "learning_strategy"
    assert results[0].concept_id == "c_fraction_addition"
    assert results[0].assist2017_concept_id == 2


def test_viking_adapter_normalizes_provider_schema_aliases() -> None:
    rag = VikingKnowledgeRAGAdapter(
        provider_name="openviking",
        provider_mode="live_provider",
        collection="assist2017-smoke",
        client=StaticRAGProviderClient(
            [
                {
                    "id": "provider-vector-001",
                    "score": 0.87,
                    "metadata": {
                        "document_id": "provider-rag-q-frac-001",
                        "document_type": "question_explanation",
                        "name": "OpenViking q_frac_001 题解",
                        "text": "先找公分母，再把分数化成同分母后相加。",
                        "source_ref": "openviking://assist2017/q_frac_001",
                        "concept_id": "c_fraction_addition",
                        "question_id": "q_frac_001",
                        "assistments2017_question_id": "3",
                        "assistments2017_concept_id": "2",
                        "canonical_mapping": {
                            "question_id": "q_frac_001",
                            "concept_id": "c_fraction_addition",
                            "assist2017_question_id": 3,
                            "assist2017_concept_id": 2,
                            "source": "openviking_fixture",
                        },
                        "coverage": {
                            "coverage_type": "question",
                            "question_aligned": True,
                            "concept_aligned": True,
                        },
                        "provenance": {"dataset": "assist2017_fixture"},
                    },
                    "raw_provider_payload": {"must_not": "leak"},
                    "embedding_vector": [0.1, 0.2, 0.3],
                }
            ]
        ),
    )

    results = rag.search(
        query="通分 题解",
        filters={"assist2017_question_id": 3, "doc_type": "question_explanation"},
        limit=1,
    )

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, RAGSearchResult)
    assert result.doc_id == "provider-rag-q-frac-001"
    assert result.doc_type == "question_explanation"
    assert result.title == "OpenViking q_frac_001 题解"
    assert result.source == "openviking://assist2017/q_frac_001"
    assert result.assist2017_question_id == 3
    assert result.assist2017_concept_id == 2
    assert result.canonical_mapping["source"] == "openviking_fixture"
    assert result.coverage["question_aligned"] is True
    assert result.provenance["provider_name"] == "openviking"
    assert result.provenance["collection"] == "assist2017-smoke"

    serialized = json.dumps(result.model_dump(), ensure_ascii=False)
    assert "raw_provider_payload" not in serialized
    assert "embedding_vector" not in serialized


def test_live_provider_mode_is_explicit_and_not_default() -> None:
    with pytest.raises(MemoryProviderConfigurationError, match="Mem0"):
        create_student_memory_store(
            MathTutorSettings(memory_provider_mode="live_provider")
        )

    with pytest.raises(RAGProviderConfigurationError, match="VikingDB/OpenViking"):
        create_knowledge_rag(MathTutorSettings(rag_provider_mode="live_provider"))

    with pytest.raises(RAGProviderConfigurationError, match="VikingDB/OpenViking"):
        create_knowledge_rag(
            MathTutorSettings(
                rag_provider_mode="live_provider",
                rag_source="imported",
            )
        )


def test_live_viking_rag_provider_smoke_from_environment() -> None:
    smoke_settings = MathTutorSettings()
    if not _live_viking_rag_smoke_enabled(smoke_settings):
        pytest.skip(
            "VikingDB/OpenViking live smoke 需要显式 run flag、endpoint、collection 和 provider API key。"
        )

    settings = MathTutorSettings(rag_provider_mode="live_provider")

    rag = create_knowledge_rag(settings)
    results = rag.search(
        query=smoke_settings.viking_rag_smoke_query or "通分 题解",
        filters={"doc_types": ["concept_note", "question_explanation", "mistake_pattern"]},
        limit=1,
    )

    assert all(isinstance(result, RAGSearchResult) for result in results)


def test_default_demo_flow_does_not_need_live_providers_or_full_data() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-provider-default-demo",
            "student_id": "student-provider-default-demo",
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommended_questions"]
    assert body["teaching_trace_summary"]["expert_evidence"]["rag_sources"]
    assert body["state_summary"]["errors"] == []
    serialized = json.dumps(body, ensure_ascii=False)
    assert "Mem0" not in serialized
    assert "VikingDB" not in serialized
    assert "OpenViking" not in serialized
    assert "checkpoint_path" not in serialized
    assert "full_assistments2017" not in serialized


def test_fake_provider_sdk_payloads_are_normalized_before_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memories = FakeStudentMemoryProvider()
    memories.write(
        StudentMemory(
            student_id="student-provider-no-leak",
            memory_type="preference",
            content="学生偏好先看分数通分的步骤化讲解。",
            evidence={"preferred_concept_id": "c_fraction_addition"},
        )
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=memories,
        rag=FakeKnowledgeRAGProvider(),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-provider-no-leak",
            "student_id": "student-provider-no-leak",
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    load_trace = next(event for event in body["teaching_trace"] if event["stage"] == "load_context")
    assert load_trace["metadata"]["memory_summaries"][0]["memory_type"] == "preference"
    assert load_trace["metadata"]["rag_sources"][0]["doc_id"].startswith("fake-rag-")
    assert body["recommended_questions"][0]["concept_id"] == "c_fraction_addition"

    serialized = json.dumps(body, ensure_ascii=False)
    for raw_provider_key in (
        "raw_provider_payload",
        "sdk_response",
        "mem0_internal_id",
        "vikingdb_distance",
        "embedding_vector",
        "provider_debug",
    ):
        assert raw_provider_key not in serialized


def _assert_student_memory_store_contract(store: StudentMemoryStore) -> None:
    student_id = "student-provider-contract"
    preference = store.write(
        StudentMemory(
            student_id=student_id,
            memory_type="preference",
            content="学生偏好步骤化讲解分数通分。",
            evidence={"preferred_concept_id": "c_fraction_addition"},
        )
    )
    mistake = store.write(
        StudentMemory(
            student_id=student_id,
            memory_type="repeated_mistake",
            content="学生在分数通分时经常忘记找公分母。",
            evidence={"concept_id": "c_fraction_addition", "question_id": "q_frac_001"},
        )
    )

    assert isinstance(preference, StudentMemory)
    assert isinstance(mistake, StudentMemory)
    assert preference.student_id == student_id
    assert preference.evidence == {"preferred_concept_id": "c_fraction_addition"}

    preference_results = store.search(
        student_id=student_id,
        query="通分 步骤",
        memory_types=["preference"],
        limit=3,
    )
    assert [memory.memory_type for memory in preference_results] == ["preference"]
    assert preference_results[0].content == preference.content

    mistake_results = store.search(
        student_id=student_id,
        query="公分母 错因",
        memory_types=["repeated_mistake"],
        limit=3,
    )
    assert [memory.memory_type for memory in mistake_results] == ["repeated_mistake"]
    assert mistake_results[0].evidence["question_id"] == "q_frac_001"

    recent = store.list_recent(student_id=student_id, limit=5)
    assert {memory.memory_id for memory in recent} == {
        preference.memory_id,
        mistake.memory_id,
    }
    detail = store.get(student_id=student_id, memory_id=preference.memory_id)
    assert detail is not None
    assert detail.memory_id == preference.memory_id
    assert detail.enabled is True
    assert detail.status == "enabled"

    disabled = store.disable(
        student_id=student_id,
        memory_id=preference.memory_id,
        reason="学生暂时不想让该偏好影响推荐。",
    )
    assert disabled is not None
    assert disabled.enabled is False
    assert disabled.status == "disabled"
    assert disabled.provenance["control"]["operation"] == "disable"
    assert disabled.provenance["control"]["reason"] == "学生暂时不想让该偏好影响推荐。"
    assert {
        memory.memory_id for memory in store.list_recent(student_id=student_id, limit=5)
    } == {preference.memory_id, mistake.memory_id}
    assert store.search(
        student_id=student_id,
        query="通分 步骤",
        memory_types=["preference"],
        limit=3,
    ) == []
    rewritten = store.write(
        StudentMemory(
            student_id=student_id,
            memory_type="preference",
            content=preference.content,
            evidence=preference.evidence,
        )
    )
    assert rewritten.enabled is False
    assert rewritten.status == "disabled"
    assert store.search(
        student_id=student_id,
        query="通分 步骤",
        memory_types=["preference"],
        limit=3,
    ) == []

    enabled = store.enable(
        student_id=student_id,
        memory_id=preference.memory_id,
        reason="学生重新允许该偏好参与学习策略。",
    )
    assert enabled is not None
    assert enabled.enabled is True
    assert enabled.status == "enabled"
    assert enabled.provenance["control"]["operation"] == "enable"
    assert store.search(
        student_id=student_id,
        query="通分 步骤",
        memory_types=["preference"],
        limit=3,
    )[0].memory_id == preference.memory_id

    deleted = store.delete(
        student_id=student_id,
        memory_id=preference.memory_id,
        reason="学生删除错误记忆。",
    )
    assert deleted is not None
    assert deleted.enabled is False
    assert deleted.status == "deleted"
    assert deleted.provenance["control"]["operation"] == "delete"
    assert deleted.provenance["control"]["reason"] == "学生删除错误记忆。"
    assert {
        memory.memory_id for memory in store.list_recent(student_id=student_id, limit=5)
    } == {mistake.memory_id}
    assert store.get(student_id=student_id, memory_id=preference.memory_id) is None
    assert store.search(
        student_id=student_id,
        query="通分 步骤",
        memory_types=["preference"],
        limit=3,
    ) == []
    assert store.enable(student_id=student_id, memory_id=preference.memory_id) is None
    rewritten_after_delete = store.write(
        StudentMemory(
            student_id=student_id,
            memory_type="preference",
            content=preference.content,
            evidence=preference.evidence,
        )
    )
    assert rewritten_after_delete.enabled is False
    assert rewritten_after_delete.status == "deleted"
    assert store.get(student_id=student_id, memory_id=preference.memory_id) is None
    assert store.search(
        student_id=student_id,
        query="通分 步骤",
        memory_types=["preference"],
        limit=3,
    ) == []

    assert store.get(student_id=student_id, memory_id="missing-memory") is None
    assert store.search(student_id="missing-student", query="通分", limit=3) == []


def _assert_knowledge_rag_contract(rag: Any) -> None:
    results = rag.search(
        query="通分 错因",
        filters={
            "doc_types": ["question_explanation", "mistake_pattern", "learning_strategy"],
            "concept_id": "c_fraction_addition",
        },
        limit=3,
    )

    assert results
    assert all(isinstance(result, RAGSearchResult) for result in results)
    assert all(result.concept_id == "c_fraction_addition" for result in results)
    assert {result.doc_type for result in results} <= {
        "question_explanation",
        "mistake_pattern",
        "learning_strategy",
    }
    first = results[0].model_dump()
    assert {"doc_id", "doc_type", "title", "content", "source", "score"} <= set(first)
    for raw_provider_key in (
        "raw_provider_payload",
        "sdk_response",
        "vikingdb_distance",
        "embedding_vector",
        "provider_debug",
    ):
        assert raw_provider_key not in first

    empty_results = rag.search(
        query="provider empty result",
        filters={"concept_id": "c_provider_missing"},
        limit=3,
    )
    assert empty_results == []


class StaticRAGProviderClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records

    def search(
        self,
        *,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        assert query
        assert limit >= 1
        return self.records


def _live_viking_rag_smoke_enabled(settings: MathTutorSettings) -> bool:
    api_key = (
        settings.openviking_api_key
        if settings.rag_live_provider == "openviking"
        else settings.vikingdb_api_key
    )
    return bool(
        settings.run_viking_rag_smoke
        and settings.rag_provider_endpoint
        and settings.rag_provider_collection
        and api_key
    )
