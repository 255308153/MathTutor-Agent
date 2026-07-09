from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.app.context.learning_context import InMemoryContextAssetStore, LearningContextLayer
from backend.app.core.config import MathTutorSettings
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.memory.mem0_provider import Mem0StudentMemoryStore
from backend.app.memory.store import MemoryProviderConfigurationError, StudentMemory, create_student_memory_store
from backend.app.schemas.learning import LearningEvent
from backend.app.storage.progress_store import InMemoryProgressStore


class FakeMem0Client:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def add(
        self,
        messages: Any,
        *,
        user_id: str,
        metadata: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        content = _message_content(messages)
        metadata = metadata or {}
        memory_id = str(metadata.get("memory_id") or f"mem0-fake-{len(self.records) + 1}")
        record = {
            "id": memory_id,
            "memory": content,
            "user_id": user_id,
            "metadata": dict(metadata),
            "score": 0.91,
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
            "raw_provider_payload": {"memory": content, "metadata": dict(metadata)},
            "sdk_response": {"object": "mem0.memory"},
            "mem0_internal_id": f"internal-{memory_id}",
            "embedding_vector": [0.1, 0.2, 0.3],
            "provider_debug": {"fixture": True},
        }
        self.records.append(record)
        return record

    def search(
        self,
        query: str,
        *,
        user_id: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        del filters
        terms = {term for term in query.lower().split() if term}
        scored = []
        for record in self.records:
            if record["user_id"] != user_id:
                continue
            haystack = " ".join(
                [
                    str(record["memory"]),
                    str(record["metadata"].get("memory_type")),
                    json.dumps(record["metadata"].get("evidence", {}), ensure_ascii=False),
                ]
            ).lower()
            score = 0.4 + min(0.5, len([term for term in terms if term in haystack]) * 0.2)
            scored.append(record | {"score": round(score, 3)})
        scored.sort(key=lambda item: (-float(item["score"]), item["id"]))
        return scored[:limit]

    def get_all(self, *, user_id: str, limit: int = 100, **_: Any) -> list[dict[str, Any]]:
        return [record for record in self.records if record["user_id"] == user_id][:limit]

    def update(
        self,
        memory_id: str,
        *,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        memory: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        for index, record in enumerate(self.records):
            if record["id"] != memory_id:
                continue
            payload = data or {}
            updated = record | {
                "memory": memory or payload.get("memory") or payload.get("text") or record["memory"],
                "metadata": metadata or payload.get("metadata") or record["metadata"],
            }
            self.records[index] = updated
            return updated
        raise KeyError(memory_id)


def test_mem0_adapter_normalizes_contract_provenance_filters_and_limits() -> None:
    store = Mem0StudentMemoryStore(client=FakeMem0Client(), api_key="test-key")
    student_id = "student-mem0-contract"

    memories = [
        _memory(student_id, "preference", "学生偏好分数通分的步骤化讲解。"),
        _memory(student_id, "repeated_mistake", "学生反复忘记寻找公分母。"),
        _memory(student_id, "effective_strategy", "画分母倍数表对学生有效。"),
        _memory(student_id, "reflection", "学生反思需要先慢读题干。"),
    ]
    for memory in memories:
        store.write(memory)

    recent = store.list_recent(student_id, limit=10)
    assert {memory.memory_type for memory in recent} == {
        "preference",
        "repeated_mistake",
        "effective_strategy",
        "reflection",
    }
    assert all(memory.source == "mem0" for memory in recent)
    assert all(memory.freshness in {"fresh", "recent", "stale"} for memory in recent)

    results = store.search(
        student_id=student_id,
        query="分数 通分 公分母",
        memory_types=["preference", "repeated_mistake"],
        limit=1,
    )

    assert len(results) == 1
    result = results[0]
    assert result.memory_type in {"preference", "repeated_mistake"}
    assert result.relevance_score is not None
    assert result.evidence["question_id"] == "q_frac_001"
    assert result.evidence["concept_id"] == "c_fraction_addition"
    assert result.provenance["source_event"] == "event:trace-contract:answer_submitted"
    assert result.provenance["trace_id"] == "trace-contract"
    assert result.provenance["provider"]["name"] == "mem0"

    serialized = json.dumps([memory.model_dump() for memory in recent], ensure_ascii=False)
    for raw_key in (
        "raw_provider_payload",
        "sdk_response",
        "mem0_internal_id",
        "embedding_vector",
        "provider_debug",
    ):
        assert raw_key not in serialized


def test_mem0_adapter_deduplicates_repeated_learning_events() -> None:
    client = FakeMem0Client()
    store = Mem0StudentMemoryStore(client=client, api_key="test-key")
    student_id = "student-mem0-dedupe"
    first = _memory(
        student_id,
        "repeated_mistake",
        "学生在分数通分时经常忘记找公分母。",
        trace_id="trace-dedupe-1",
    )
    repeated = _memory(
        student_id,
        "repeated_mistake",
        "学生在分数通分时经常忘记找公分母。",
        trace_id="trace-dedupe-2",
    )

    written_first = store.write(first)
    written_second = store.write(repeated)

    assert written_first.memory_id == written_second.memory_id
    assert len(client.records) == 1
    recent = store.list_recent(student_id, limit=1)[0]
    assert recent.provenance["trace_ids"] == ["trace-dedupe-1", "trace-dedupe-2"]
    assert recent.provenance["event_sources"] == [
        "event:trace-dedupe-1:answer_submitted",
        "event:trace-dedupe-2:answer_submitted",
    ]


def test_mem0_cross_session_smoke_recalls_memory_and_changes_strategy_language() -> None:
    store = Mem0StudentMemoryStore(client=FakeMem0Client(), api_key="test-key")
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=store,
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    student_id = "student-mem0-cross-session"

    first_session = loop.handle_event(
        LearningEvent(
            session_id="session-mem0-cross-1",
            student_id=student_id,
            type="answer_submitted",
            message="我先提交一次错误答案。",
            payload={"question_id": "q_frac_001", "answer": "1/6"},
        )
    )
    assert first_session.teaching_trace[-1].metadata["memory_update_count"] == 1

    second_session = loop.handle_event(
        LearningEvent(
            session_id="session-mem0-cross-2",
            student_id=student_id,
            type="chat_message",
            message="下一步怎么复习分数通分？",
            payload={},
        )
    )

    expert = second_session.teaching_trace_summary.expert_evidence
    assert any(
        memory["memory_type"] == "repeated_mistake"
        for memory in expert["student_memories"]
    )
    assert "我会参考你之前的学习偏好" in second_session.response
    assert any(
        "参考重复错因" in question["reason"]
        for question in second_session.recommended_questions
    )


def test_mem0_memory_cannot_overwrite_authoritative_kt_facts() -> None:
    store = Mem0StudentMemoryStore(client=FakeMem0Client(), api_key="test-key")
    student_id = "student-mem0-boundary"
    concept_id = "c_fraction_addition"
    store.write(
        StudentMemory(
            student_id=student_id,
            memory_type="preference",
            content="学生偏好分数通分的步骤化讲解。",
            evidence={
                "preferred_concept_id": concept_id,
                "concept_id": concept_id,
                "question_id": "q_frac_001",
                "mastery_by_concept": {concept_id: 1.0},
                "prediction_probability": 0.99,
                "weak_concepts": [],
                "forgetting_risks": [],
            },
            provenance=_provenance("trace-boundary", "session-old"),
        )
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=store,
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )

    response = loop.handle_event(
        LearningEvent(
            session_id="session-mem0-boundary",
            student_id=student_id,
            type="answer_submitted",
            message="我提交一个错误答案，验证 memory 不能改写 KT facts。",
            payload={"question_id": "q_frac_001", "answer": "1/6"},
        )
    )

    expert = response.teaching_trace_summary.expert_evidence
    assembled = expert["assembled_context"]
    kt_diagnosis = expert["kt_diagnosis"]

    assert assembled["authoritative_kt_facts"]["weak_concepts"] == kt_diagnosis["weak_concepts"]
    assert assembled["authoritative_kt_facts"]["forgetting_risks"] == kt_diagnosis[
        "forgetting_risks"
    ]
    assert assembled["authoritative_kt_facts"]["prediction_probability"] == 0.58
    assert assembled["authoritative_kt_facts"]["mastery_by_concept"][concept_id] != 1.0
    assert response.state_summary["weak_concepts"] == kt_diagnosis["weak_concepts"]
    assert response.state_summary["forgetting_risks"] == kt_diagnosis["forgetting_risks"]

    memory_context = assembled["normalized_context"]["student_memory"][0]
    assert memory_context["metadata"]["evidence"]["prediction_probability"] == 0.99
    assert memory_context["metadata"]["evidence"]["mastery_by_concept"][concept_id] == 1.0


@pytest.mark.skipif(
    os.getenv("MATHTUTOR_RUN_MEM0_LIVE_SMOKE") != "1"
    or not os.getenv("MATHTUTOR_MEM0_API_KEY"),
    reason="Mem0 live smoke 需要显式 MATHTUTOR_RUN_MEM0_LIVE_SMOKE=1 和 API key。",
)
def test_mem0_live_provider_smoke_is_opt_in() -> None:
    try:
        store = create_student_memory_store(
            MathTutorSettings(
                memory_provider_mode="live_provider",
                mem0_api_key=str(os.environ["MATHTUTOR_MEM0_API_KEY"]),
            )
        )
    except MemoryProviderConfigurationError as exc:
        pytest.skip(f"Mem0 SDK 不可用或配置不完整：{exc}")

    student_id = f"student-live-mem0-smoke-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    store.write(_memory(student_id, "reflection", "live smoke 反思记忆。"))
    results = store.search(student_id=student_id, query="live smoke 反思", limit=3)
    assert any(memory.memory_type == "reflection" for memory in results)


def _memory(
    student_id: str,
    memory_type: str,
    content: str,
    *,
    trace_id: str = "trace-contract",
) -> StudentMemory:
    return StudentMemory(
        student_id=student_id,
        memory_type=memory_type,  # type: ignore[arg-type]
        content=content,
        evidence={
            "question_id": "q_frac_001",
            "concept_id": "c_fraction_addition",
            "source_event": f"event:{trace_id}:answer_submitted",
            "trace_id": trace_id,
            "event_time": "2026-07-09T06:00:00+00:00",
        },
        provenance=_provenance(trace_id, "session-contract"),
    )


def _provenance(trace_id: str, session_id: str) -> dict[str, Any]:
    return {
        "source_event": f"event:{trace_id}:answer_submitted",
        "trace_id": trace_id,
        "session_id": session_id,
        "event_type": "answer_submitted",
        "occurred_at": "2026-07-09T06:00:00+00:00",
    }


def _message_content(messages: Any) -> str:
    if isinstance(messages, str):
        return messages
    if isinstance(messages, list) and messages:
        first = messages[0]
        if isinstance(first, dict) and first.get("content"):
            return str(first["content"])
    return str(messages)
