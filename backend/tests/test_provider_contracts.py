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
from backend.app.storage.progress_store import InMemoryProgressStore


def test_default_provider_modes_keep_demo_mock_local_fallback() -> None:
    settings = MathTutorSettings()

    assert settings.memory_provider_mode == "local_fallback"
    assert settings.rag_provider_mode == "local_fallback"
    assert settings.assist2017_dataset_mode == "demo"
    assert settings.content_source == "demo"
    assert settings.rag_source == "demo"
    assert settings.kt_engine == "mock"
    assert settings.mem0_api_key == ""
    assert settings.vikingdb_api_key == ""
    assert settings.openviking_api_key == ""
    assert isinstance(create_student_memory_store(settings), InMemoryStudentMemoryStore)
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


def test_live_provider_mode_is_explicit_and_not_default() -> None:
    with pytest.raises(MemoryProviderConfigurationError, match="Mem0"):
        create_student_memory_store(
            MathTutorSettings(memory_provider_mode="live_provider")
        )

    with pytest.raises(RAGProviderConfigurationError, match="VikingDB/OpenViking"):
        create_knowledge_rag(MathTutorSettings(rag_provider_mode="live_provider"))


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
    load_trace = body["teaching_trace"][0]
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
