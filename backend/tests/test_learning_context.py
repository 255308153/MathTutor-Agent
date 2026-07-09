from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from backend.app.context.learning_context import (
    AssembledContext,
    ContextAsset,
    InMemoryContextAssetStore,
    LearningContextLayer,
)
from backend.app.main import create_app
from backend.app.memory.store import InMemoryStudentMemoryStore, StudentMemory
from backend.app.rag.schema import RAGSearchResult
from backend.app.schemas.learning import KTLearningProgress, LearningEvent


class EmptyRAG:
    def search(
        self,
        query: str,
        filters: dict[str, object] | None = None,
        limit: int = 3,
    ) -> list[RAGSearchResult]:
        return []


def test_context_asset_schema_supports_five_asset_types() -> None:
    asset_types = [
        "student_memory",
        "knowledge_resource",
        "task_state",
        "tool_observation",
        "trace_reference",
    ]

    for asset_type in asset_types:
        asset = ContextAsset(
            asset_type=asset_type,
            source_type="test",
            source_ref=f"test:{asset_type}",
            summary=f"{asset_type} summary",
            student_id="student-context-schema",
            session_id="session-context-schema",
            confidence=0.9,
            freshness="fresh",
            included_reason="schema coverage",
        )
        assert asset.asset_id.startswith("ctx-")
        assert asset.asset_type == asset_type

    with pytest.raises(ValidationError):
        ContextAsset(
            asset_type="mastery_fact",
            source_type="test",
            source_ref="test:bad",
            summary="bad",
            confidence=1.4,
        )


def test_context_asset_store_filters_and_orders_assets() -> None:
    store = InMemoryContextAssetStore()
    old = store.write(
        ContextAsset(
            asset_id="ctx-old",
            asset_type="knowledge_resource",
            source_type="rag",
            source_ref="rag:old",
            summary="older fraction note",
            student_id="student-store",
            session_id="session-store",
            concept_id="c_fraction_addition",
            confidence=0.7,
            freshness="recent",
        )
    )
    fresh = store.write(
        ContextAsset(
            asset_id="ctx-fresh",
            asset_type="student_memory",
            source_type="memory",
            source_ref="mem:fresh",
            summary="student prefers worked examples",
            student_id="student-store",
            session_id="session-store",
            concept_id="c_fraction_addition",
            question_id="q_frac_001",
            confidence=0.95,
            freshness="fresh",
        )
    )
    store.write(
        ContextAsset(
            asset_id="ctx-other",
            asset_type="task_state",
            source_type="progress",
            source_ref="progress:other",
            summary="other student state",
            student_id="student-other",
            confidence=1.0,
        )
    )

    results = store.search(
        student_id="student-store",
        asset_types=["student_memory", "knowledge_resource"],
        concept_id="c_fraction_addition",
    )

    assert [asset.asset_id for asset in results] == [fresh.asset_id, old.asset_id]
    assert store.search(student_id="student-store", question_id="q_frac_001")[0].asset_id == "ctx-fresh"


def test_context_asset_store_filters_source_freshness_confidence_and_relevance() -> None:
    store = InMemoryContextAssetStore()
    exact = store.write(
        ContextAsset(
            asset_id="ctx-exact",
            asset_type="task_state",
            source_type="learning_loop_event",
            source_ref="event:exact",
            summary="current exact question task",
            student_id="student-filter",
            session_id="session-filter",
            concept_id="c_fraction_addition",
            question_id="q_frac_001",
            confidence=0.7,
            freshness="fresh",
        )
    )
    higher_confidence_but_less_relevant = store.write(
        ContextAsset(
            asset_id="ctx-concept",
            asset_type="student_memory",
            source_type="student_memory_store",
            source_ref="memory:concept",
            summary="concept memory",
            student_id="student-filter",
            session_id="session-filter",
            concept_id="c_fraction_addition",
            confidence=0.95,
            freshness="fresh",
        )
    )
    store.write(
        ContextAsset(
            asset_id="ctx-stale",
            asset_type="student_memory",
            source_type="student_memory_store",
            source_ref="memory:stale",
            summary="stale memory",
            student_id="student-filter",
            session_id="session-filter",
            concept_id="c_fraction_addition",
            confidence=0.99,
            freshness="stale",
        )
    )
    store.write(
        ContextAsset(
            asset_id="ctx-low",
            asset_type="knowledge_resource",
            source_type="local_rag",
            source_ref="rag:low",
            summary="low confidence doc",
            student_id="student-filter",
            session_id="session-filter",
            concept_id="c_fraction_addition",
            confidence=0.2,
            freshness="fresh",
        )
    )

    results = store.search(
        student_id="student-filter",
        session_id="session-filter",
        source_types=["learning_loop_event", "student_memory_store"],
        freshness=["fresh"],
        min_confidence=0.6,
        concept_id="c_fraction_addition",
        question_id="q_frac_001",
        intent="answer_submission",
    )

    assert [asset.asset_id for asset in results] == [
        exact.asset_id,
        higher_confidence_but_less_relevant.asset_id,
    ]


def test_learning_context_layer_assembles_context_without_overwriting_kt_facts() -> None:
    layer = LearningContextLayer(store=InMemoryContextAssetStore())
    kt_facts = {
        "weak_concepts": [{"concept_id": "c_fraction_addition", "mastery": 0.42}],
        "forgetting_risks": [{"concept_id": "c_fraction_addition", "forgetting_risk": 0.6}],
        "prediction_probability": 0.58,
        "mastery_by_concept": {"c_fraction_addition": 0.42},
    }
    assets = [
        ContextAsset(
            asset_id="ctx-memory",
            asset_type="student_memory",
            source_type="memory",
            source_ref="mem:1",
            summary="Student likes visual hints.",
            student_id="student-assemble",
            confidence=0.9,
            metadata={
                "weak_concepts": [{"concept_id": "fake", "mastery": 1.0}],
                "prediction_probability": 0.99,
            },
        )
    ]

    assembled = layer.assemble_context(
        intent="next_step_advice",
        assets=assets,
        kt_facts=kt_facts,
        token_budget=256,
    )

    assert isinstance(assembled, AssembledContext)
    assert assembled.authoritative_kt_facts == kt_facts
    assert assembled.context_invariants["context_boundary"] == (
        "Context can assemble evidence, not decide learning facts."
    )
    assert assembled.asset_summaries[0]["summary"] == "Student likes visual hints."
    assert assembled.normalized_context["student_memory"][0]["kind"] == "student_memory"
    assert assembled.evidence_gaps[0]["reason"] == "RAG 未找到相关知识资源"


def test_learning_context_layer_normalizes_memory_rag_and_evidence_gaps() -> None:
    layer = LearningContextLayer(store=InMemoryContextAssetStore())
    kt_facts = {
        "weak_concepts": [],
        "forgetting_risks": [],
        "prediction_probability": 0.58,
        "mastery_by_concept": {"c_fraction_addition": 0.4},
    }
    assets = [
        ContextAsset(
            asset_type="student_memory",
            source_type="student_memory_store",
            source_ref="memory:pref",
            summary="学生偏好步骤化讲解。",
            metadata={
                "memory_type": "preference",
                "normalized_kind": "preference",
                "evidence": {"preferred_teaching_type": "procedure"},
            },
            included_reason="参考学生偏好",
        ),
        ContextAsset(
            asset_type="knowledge_resource",
            source_type="local_rag",
            source_ref="rag:strategy",
            summary="下一步练习策略：薄弱优先，难度适中",
            metadata={
                "doc_type": "learning_strategy",
                "normalized_kind": "learning_strategy",
                "source": "demo-rag/learning_strategies.md#next-step",
            },
            included_reason="参考学习策略资源",
        ),
    ]

    assembled = layer.assemble_context(
        intent="next_step_advice",
        assets=assets,
        kt_facts=kt_facts,
    )

    normalized = assembled.normalized_context
    assert normalized["strategy_hints"]["preferred_teaching_type"] == "procedure"
    assert normalized["student_memory"][0]["included_reason"] == "参考学生偏好"
    assert normalized["knowledge_resource"][0]["kind"] == "learning_strategy"
    assert normalized["knowledge_hints"]["resource_count"] == 1
    assert assembled.evidence_gaps == []

    no_knowledge = layer.assemble_context(
        intent="next_step_advice",
        assets=assets[:1],
        kt_facts=kt_facts,
    )
    assert no_knowledge.evidence_gaps == [
        {
            "gap_type": "knowledge_resource",
            "reason": "RAG 未找到相关知识资源",
            "impact": "no knowledge_resource asset was fabricated",
        }
    ]


def test_learning_context_layer_omits_disabled_memory_with_reason() -> None:
    layer = LearningContextLayer(store=InMemoryContextAssetStore())
    disabled_memory = StudentMemory(
        student_id="student-disabled-context",
        memory_type="preference",
        content="学生偏好先练比例题。",
        evidence={"preferred_concept_id": "c_ratio"},
        enabled=False,
        status="disabled",
        provenance={
            "control": {
                "operation": "disable",
                "reason": "学生禁用该记忆，默认学习上下文排除。",
            }
        },
    )
    assets = layer.collect_assets(
        student_id="student-disabled-context",
        session_id="session-disabled-context",
        intent="next_step_advice",
        learning_event=LearningEvent(
            session_id="session-disabled-context",
            student_id="student-disabled-context",
            type="chat_message",
            message="推荐下一题",
            payload={},
        ),
        kt_progress=KTLearningProgress(student_id="student-disabled-context"),
        student_memories=[disabled_memory.model_dump()],
        rag_context=[],
        kt_facts={"weak_concepts": [], "forgetting_risks": []},
        trace_id="trace-disabled-context",
    )

    assembled = layer.assemble_context(
        intent="next_step_advice",
        assets=assets,
        kt_facts={"weak_concepts": [], "forgetting_risks": []},
    )

    assert assembled.normalized_context["student_memory"] == []
    omitted_memory = next(
        item for item in assembled.asset_selection["omitted"]
        if item["asset_type"] == "student_memory"
    )
    assert omitted_memory["excluded_reason"] == "学生已禁用该记忆，默认学习上下文已排除。"
    assert assembled.normalized_context["strategy_hints"]["preferred_concept_id"] is None


def test_context_assembler_trims_budget_and_reports_included_excluded_reasons() -> None:
    layer = LearningContextLayer(store=InMemoryContextAssetStore())
    assets = [
        ContextAsset(
            asset_id="ctx-task-budget",
            asset_type="task_state",
            source_type="learning_loop_state",
            source_ref="progress:budget",
            summary="current task",
            included_reason="纳入当前任务状态快照",
            confidence=1.0,
            freshness="fresh",
        ),
        ContextAsset(
            asset_id="ctx-memory-budget",
            asset_type="student_memory",
            source_type="student_memory_store",
            source_ref="memory:budget",
            summary="学生偏好步骤化讲解。",
            metadata={"memory_type": "preference", "normalized_kind": "preference"},
            included_reason="参考学生偏好",
            confidence=0.9,
            freshness="recent",
        ),
        ContextAsset(
            asset_id="ctx-knowledge-budget",
            asset_type="knowledge_resource",
            source_type="local_rag",
            source_ref="rag:budget",
            summary="very large knowledge resource",
            content_preview="知识资源 " * 80,
            metadata={"doc_type": "concept_note", "normalized_kind": "concept_note"},
            included_reason="参考相关知识资源",
            confidence=0.8,
            freshness="fresh",
        ),
    ]

    assembled = layer.assemble_context(
        intent="next_step_advice",
        assets=assets,
        kt_facts={"prediction_probability": 0.58},
        token_budget=6,
    )

    selected_ids = {
        summary["asset_id"]
        for summary in assembled.asset_summaries
        if summary["selection_status"] == "included"
    }
    excluded = {
        summary["asset_id"]: summary
        for summary in assembled.asset_summaries
        if summary["selection_status"] == "excluded"
    }
    assert selected_ids == {"ctx-task-budget", "ctx-memory-budget"}
    assert excluded["ctx-knowledge-budget"]["excluded_reason"] == (
        "超出上下文预算，已裁剪低优先级资产"
    )
    assert assembled.budget_used <= assembled.budget_limit == 6
    assert {summary["asset_id"] for summary in assembled.asset_selection["selected"]} == selected_ids
    assert {
        summary["asset_id"] for summary in assembled.asset_selection["omitted"]
    } == {"ctx-knowledge-budget"}
    assert assembled.compression_summary["excluded_asset_count"] == 1
    assert assembled.normalized_context["student_memory"][0]["summary"] == "学生偏好步骤化讲解。"
    assert any(gap["gap_type"] == "context_budget" for gap in assembled.evidence_gaps)


def test_provider_backed_assets_are_budgeted_without_flooding_context() -> None:
    layer = LearningContextLayer(store=InMemoryContextAssetStore())
    assets = [
        ContextAsset(
            asset_id="ctx-provider-memory",
            asset_type="student_memory",
            source_type="provider_memory",
            source_ref="memory:fake-provider",
            summary="学生偏好步骤化讲解。",
            metadata={
                "memory_type": "preference",
                "normalized_kind": "preference",
                "provider_backed": True,
                "provider_name": "fake_mem0_fixture",
                "provider_mode": "fake_provider",
            },
            included_reason="参考学生偏好",
            confidence=0.95,
            freshness="fresh",
        ),
        ContextAsset(
            asset_id="ctx-provider-rag-short",
            asset_type="knowledge_resource",
            source_type="provider_rag",
            source_ref="rag:fake-short",
            summary="provider RAG 题解",
            metadata={
                "doc_type": "question_explanation",
                "normalized_kind": "question_explanation",
                "provider_backed": True,
                "provider_name": "fake_vikingdb",
                "provider_mode": "fake_provider",
            },
            included_reason="参考题目解析资源",
            confidence=0.9,
            freshness="fresh",
        ),
        ContextAsset(
            asset_id="ctx-provider-rag-large",
            asset_type="knowledge_resource",
            source_type="provider_rag",
            source_ref="rag:fake-large",
            summary="provider RAG 长文档",
            content_preview="provider-backed knowledge " * 80,
            metadata={
                "doc_type": "learning_strategy",
                "normalized_kind": "learning_strategy",
                "provider_backed": True,
                "provider_name": "fake_vikingdb",
                "provider_mode": "fake_provider",
            },
            included_reason="参考学习策略资源",
            confidence=0.82,
            freshness="fresh",
        ),
    ]

    assembled = layer.assemble_context(
        intent="next_step_advice",
        assets=assets,
        kt_facts={"prediction_probability": 0.58},
        token_budget=8,
    )

    selected_ids = {summary["asset_id"] for summary in assembled.asset_selection["selected"]}
    omitted_ids = {summary["asset_id"] for summary in assembled.asset_selection["omitted"]}
    assert {"ctx-provider-memory", "ctx-provider-rag-short"} <= selected_ids
    assert "ctx-provider-rag-large" in omitted_ids
    assert any(gap["gap_type"] == "context_budget" for gap in assembled.evidence_gaps)
    assert assembled.budget_used <= assembled.budget_limit == 8


def test_context_assembler_reports_stale_low_confidence_and_provider_gaps() -> None:
    layer = LearningContextLayer(store=InMemoryContextAssetStore())
    assets = [
        ContextAsset(
            asset_id="ctx-stale-task",
            asset_type="task_state",
            source_type="learning_loop_state",
            source_ref="progress:stale",
            summary="old task state",
            confidence=0.9,
            freshness="stale",
        ),
        ContextAsset(
            asset_id="ctx-memory-gap",
            asset_type="student_memory",
            source_type="student_memory_store",
            source_ref="memory:gap",
            summary="学生偏好图示。",
            confidence=0.9,
            freshness="recent",
        ),
        ContextAsset(
            asset_id="ctx-low-observation",
            asset_type="tool_observation",
            source_type="rag",
            source_ref="rag:low-confidence",
            summary="low confidence retrieval",
            confidence=0.3,
            freshness="fresh",
        ),
        ContextAsset(
            asset_id="ctx-provider-failure",
            asset_type="knowledge_resource",
            source_type="vikingdb_failure",
            source_ref="provider:vikingdb",
            summary="provider failure placeholder",
            metadata={"provider_error": "timeout"},
            excluded_reason="provider failure",
            confidence=0.1,
            freshness="fresh",
        ),
    ]

    assembled = layer.assemble_context(
        intent="answer_submission",
        assets=assets,
        kt_facts={"prediction_probability": 0.58},
        token_budget=64,
    )

    gap_types = {gap["gap_type"] for gap in assembled.evidence_gaps}
    assert {
        "knowledge_resource",
        "stale_task_state",
        "low_confidence_observation",
        "provider_failure",
    }.issubset(gap_types)
    omitted = [
        summary
        for summary in assembled.asset_summaries
        if summary["asset_id"] == "ctx-provider-failure"
    ][0]
    assert omitted["selection_status"] == "excluded"
    assert omitted["excluded_reason"] == "provider failure"


def test_next_step_api_generates_assembled_context_and_preserves_kt_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    memories = InMemoryStudentMemoryStore()
    memories.write(
        StudentMemory(
            student_id="student-context-api",
            memory_type="preference",
            content="学生偏好步骤化讲解。",
            evidence={"preferred_teaching_type": "procedure"},
        )
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=memories,
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-api",
            "student_id": "student-context-api",
            "type": "chat_message",
            "message": "我下一步应该学什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    kt_diagnosis = expert["kt_diagnosis"]

    assert "context_assemble" in body["teaching_trace_summary"]["stages"]
    assert expert["context_assets"]
    assert assembled["budget_used"] <= assembled["budget_limit"]
    assert assembled["compression_summary"]["strategy"] == "priority_budget_summary"
    assert assembled["asset_summaries"][0]["selection_status"] == "included"
    assert assembled["authoritative_kt_facts"]["weak_concepts"] == kt_diagnosis["weak_concepts"]
    assert assembled["authoritative_kt_facts"]["forgetting_risks"] == kt_diagnosis["forgetting_risks"]
    assert (
        assembled["authoritative_kt_facts"]["prediction_probability"]
        == kt_diagnosis["prediction_probability"]
    )
    assert body["state_summary"]["weak_concepts"] == kt_diagnosis["weak_concepts"]
    assert body["state_summary"]["forgetting_risks"] == kt_diagnosis["forgetting_risks"]
    assert "Context can assemble evidence, not decide learning facts." in body[
        "teaching_trace_summary"
    ]["invariants"]


def test_next_step_api_consumes_student_memory_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    memories = InMemoryStudentMemoryStore()
    memories.write(
        StudentMemory(
            student_id="student-context-memory",
            memory_type="preference",
            content="学生偏好步骤化讲解，并希望先练比例题。",
            evidence={
                "preferred_teaching_type": "procedure",
                "preferred_concept_id": "c_ratio",
            },
        )
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=memories,
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-memory",
            "student_id": "student-context-memory",
            "type": "chat_message",
            "message": "推荐下一题",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    normalized = assembled["normalized_context"]

    assert normalized["strategy_hints"]["preferred_concept_id"] == "c_ratio"
    assert normalized["student_memory"][0]["included_reason"] == "参考学生偏好"
    assert "参考学生偏好" in body["recommended_questions"][0]["reason"]
    assert "参考学生偏好" in expert["planner_decision"]["evidence"]["context_included_reasons"]
    assert body["recommended_questions"][0]["concept_id"] == "c_ratio"


def test_next_step_api_excludes_disabled_memory_from_search_and_old_context_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    student_id = "student-context-disabled-memory"
    memories = InMemoryStudentMemoryStore()
    memory = memories.write(
        StudentMemory(
            student_id=student_id,
            memory_type="preference",
            content="学生偏好步骤化讲解，并希望先练比例题。",
            evidence={
                "preferred_teaching_type": "procedure",
                "preferred_concept_id": "c_ratio",
            },
        )
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=memories,
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    first_response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-disabled-memory",
            "student_id": student_id,
            "type": "chat_message",
            "message": "推荐下一题",
            "payload": {},
        },
    )
    assert first_response.status_code == 200
    assert "参考学生偏好" in first_response.json()["recommended_questions"][0]["reason"]

    disabled = memories.disable(
        student_id=student_id,
        memory_id=memory.memory_id,
        reason="学生暂时不想让该偏好影响推荐。",
    )
    assert disabled is not None

    second_response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-disabled-memory",
            "student_id": student_id,
            "type": "chat_message",
            "message": "推荐下一题",
            "payload": {},
        },
    )

    assert second_response.status_code == 200
    body = second_response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    selected = assembled["asset_selection"]["selected"]
    omitted = assembled["asset_selection"]["omitted"]

    assert expert["student_memories"] == []
    assert assembled["normalized_context"]["student_memory"] == []
    assert not any(asset["asset_type"] == "student_memory" for asset in selected)
    assert any(
        asset["asset_type"] == "student_memory"
        and asset["excluded_reason"] == "学生已禁用该记忆，默认学习上下文已排除。"
        for asset in omitted
    )
    assert "参考学生偏好" not in body["recommended_questions"][0]["reason"]
    assert "参考你之前的学习偏好" not in body["response"]
    assert "参考学生偏好" not in expert["planner_decision"]["evidence"][
        "context_included_reasons"
    ]


def test_next_step_api_consumes_knowledge_resource_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=InMemoryStudentMemoryStore(),
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-rag",
            "student_id": "student-context-rag",
            "type": "chat_message",
            "message": "下一步应该学什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    knowledge = assembled["normalized_context"]["knowledge_resource"]

    assert knowledge
    assert {asset["kind"] for asset in knowledge} & {"concept_note", "learning_strategy"}
    assert "参考相关知识资源" in body["recommended_questions"][0]["reason"] or (
        "参考学习策略资源" in body["recommended_questions"][0]["reason"]
    )
    assert not [
        gap for gap in assembled["evidence_gaps"] if gap["gap_type"] == "knowledge_resource"
    ]


def test_next_step_api_marks_memory_gap_for_new_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=InMemoryStudentMemoryStore(),
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-no-memory",
            "student_id": "student-context-no-memory",
            "type": "chat_message",
            "message": "推荐下一题",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assembled = body["teaching_trace_summary"]["expert_evidence"]["assembled_context"]
    context_assets = body["teaching_trace_summary"]["expert_evidence"]["context_assets"]

    assert body["recommended_questions"]
    assert not [asset for asset in context_assets if asset["asset_type"] == "student_memory"]
    assert {
        "gap_type": "student_memory",
        "reason": "无可用记忆",
        "impact": "recommendation uses KT facts and content only",
    } in assembled["evidence_gaps"]
    assert "无可用记忆" in body["recommended_questions"][0]["reason"]


def test_next_step_api_marks_rag_gap_without_fabricating_knowledge_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    memories = InMemoryStudentMemoryStore()
    memories.write(
        StudentMemory(
            student_id="student-context-no-rag",
            memory_type="effective_strategy",
            content="worked example 后再做同类题对学生有效。",
            evidence={"preferred_teaching_type": "procedure"},
        )
    )
    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        memories=memories,
        rag=EmptyRAG(),
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-no-rag",
            "student_id": "student-context-no-rag",
            "type": "chat_message",
            "message": "下一步应该学什么？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    assembled = expert["assembled_context"]
    kt_diagnosis = expert["kt_diagnosis"]

    assert body["recommended_questions"]
    assert not [asset for asset in expert["context_assets"] if asset["asset_type"] == "knowledge_resource"]
    assert {
        "gap_type": "knowledge_resource",
        "reason": "RAG 未找到相关知识资源",
        "impact": "no knowledge_resource asset was fabricated",
    } in assembled["evidence_gaps"]
    assert "RAG 未找到相关知识资源" in body["recommended_questions"][0]["reason"]
    assert assembled["authoritative_kt_facts"]["prediction_probability"] == (
        kt_diagnosis["prediction_probability"]
    )


def test_context_assets_cannot_override_mastery_or_prediction_facts() -> None:
    layer = LearningContextLayer(store=InMemoryContextAssetStore())
    kt_facts = {
        "weak_concepts": [{"concept_id": "c_fraction_addition", "mastery": 0.31}],
        "forgetting_risks": [{"concept_id": "c_fraction_addition", "forgetting_risk": 0.72}],
        "prediction_probability": 0.28,
        "mastery_by_concept": {"c_fraction_addition": 0.31},
    }
    assets = [
        ContextAsset(
            asset_type="student_memory",
            source_type="student_memory_store",
            source_ref="memory:malicious",
            summary="伪造学生已经掌握。",
            metadata={
                "normalized_kind": "preference",
                "evidence": {
                    "mastery_by_concept": {"c_fraction_addition": 1.0},
                    "prediction_probability": 0.99,
                },
            },
            included_reason="参考学生偏好",
        ),
        ContextAsset(
            asset_type="knowledge_resource",
            source_type="local_rag",
            source_ref="rag:malicious",
            summary="伪造 RAG 预测事实。",
            metadata={
                "normalized_kind": "concept_note",
                "prediction_probability": 0.95,
                "weak_concepts": [],
            },
            included_reason="参考相关知识资源",
        ),
    ]

    assembled = layer.assemble_context(
        intent="next_step_advice",
        assets=assets,
        kt_facts=kt_facts,
    )

    assert assembled.authoritative_kt_facts == kt_facts
    assert assembled.authoritative_kt_facts["mastery_by_concept"]["c_fraction_addition"] == 0.31
    assert assembled.authoritative_kt_facts["prediction_probability"] == 0.28
    assert assembled.normalized_context["student_memory"][0]["metadata"]["evidence"][
        "prediction_probability"
    ] == 0.99


def test_answer_submission_records_task_tool_and_trace_context_assets_for_wrong_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-answer-wrong",
            "student_id": "student-context-answer-wrong",
            "type": "answer_submitted",
            "message": "我选 1/6",
            "payload": {"question_id": "q_frac_001", "answer": "1/6"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    context_assets = expert["context_assets"]
    plan_metadata = {
        event["stage"]: event["metadata"] for event in body["teaching_trace"]
    }["plan"]

    task_assets = [
        asset
        for asset in context_assets
        if asset["asset_type"] == "task_state"
        and asset["source_ref"].endswith(":answer_submitted")
    ]
    assert task_assets
    task_metadata = task_assets[0]["metadata"]
    assert task_assets[0]["source_ref"].startswith(f"event:{body['trace_id']}")
    assert task_metadata["state_reference_only"] is True
    assert task_metadata["submitted_answer"] == "1/6"
    assert task_metadata["grading_result"]["is_correct"] is False
    assert task_metadata["next_action"]["type"].endswith("_after_mistake")

    tool_assets = [
        asset for asset in context_assets if asset["asset_type"] == "tool_observation"
    ]
    tool_sources = {asset["source_type"] for asset in tool_assets}
    assert {"kt", "rag", "mistake_diagnoser", "recommender"}.issubset(tool_sources)

    kt_asset = next(asset for asset in tool_assets if asset["source_type"] == "kt")
    assert kt_asset["metadata"]["snapshot"] is True
    assert kt_asset["metadata"]["source"] == "kt"
    assert kt_asset["metadata"]["trace_id"] == body["trace_id"]
    assert kt_asset["metadata"]["generated_at"]
    assert kt_asset["freshness"] == "fresh"
    assert kt_asset["metadata"]["prediction_probability"] == expert["kt_diagnosis"][
        "prediction_probability"
    ]

    rag_asset = next(asset for asset in tool_assets if asset["source_type"] == "rag")
    assert rag_asset["metadata"]["source_count"] >= 1
    mistake_asset = next(
        asset for asset in tool_assets if asset["source_type"] == "mistake_diagnoser"
    )
    assert mistake_asset["included_reason"] == "记录错因诊断工具观察快照"
    assert mistake_asset["metadata"]["mistake_diagnosis"]["concept"]["concept_id"] == (
        "c_fraction_addition"
    )

    trace_asset = next(
        asset
        for asset in context_assets
        if asset["asset_type"] == "trace_reference"
        and asset["source_ref"].endswith(":answer_submission")
    )
    assert trace_asset["metadata"]["decision_ref"] == f"planner:{body['trace_id']}"
    assert trace_asset["metadata"]["memory_update_source"] == (
        f"event:{body['trace_id']}:answer_submitted"
    )

    selected = plan_metadata["context_asset_selection"]["selected"]
    assert any(asset["source_type"] == "kt" for asset in selected)
    assert any(asset["source_type"] == "recommender" for asset in selected)
    assert expert["context_asset_selection"]["selected"]
    assert expert["assembled_context"]["authoritative_kt_facts"]["prediction_probability"] == (
        expert["kt_diagnosis"]["prediction_probability"]
    )
    assert expert["assembled_context"]["budget_used"] <= expert["assembled_context"]["budget_limit"]
    assert expert["assembled_context"]["compression_summary"]["strategy"] == (
        "priority_budget_summary"
    )
    assert all(
        "selection_status" in summary
        for summary in expert["assembled_context"]["asset_summaries"]
    )
    assert body["state_summary"]["weak_concepts"] == expert["kt_diagnosis"]["weak_concepts"]


def test_answer_submission_records_omitted_mistake_snapshot_for_correct_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-answer-correct",
            "student_id": "student-context-answer-correct",
            "type": "answer_submitted",
            "message": "答案是 3/4",
            "payload": {"question_id": "q_frac_001", "answer": "3/4"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    context_assets = expert["context_assets"]
    plan_metadata = {
        event["stage"]: event["metadata"] for event in body["teaching_trace"]
    }["plan"]

    task_asset = next(
        asset
        for asset in context_assets
        if asset["asset_type"] == "task_state"
        and asset["source_ref"].endswith(":answer_submitted")
    )
    assert task_asset["metadata"]["grading_result"]["is_correct"] is True
    assert task_asset["metadata"]["next_action"]["type"] == "reinforce_mastery"

    omitted = plan_metadata["context_asset_selection"]["omitted"]
    assert any(
        asset["source_type"] == "mistake_diagnoser"
        and asset["excluded_reason"] == "正确作答或未判题，本轮没有错因诊断"
        for asset in omitted
    )
    assert any(
        asset["source_type"] == "mistake_diagnoser"
        for asset in expert["context_asset_selection"]["omitted"]
    )
    assert expert["kt_diagnosis"]["prediction_probability"] == 0.58
    assert expert["assembled_context"]["authoritative_kt_facts"]["prediction_probability"] == 0.58


def test_ungraded_answer_submission_records_task_tool_and_trace_context_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import events as events_api
    from backend.app.graph.learning_loop import MathTutorLearningLoop
    from backend.app.storage.progress_store import InMemoryProgressStore

    class MissingAnswerRepository:
        def get_question(self, question_id: str) -> dict[str, object] | None:
            if question_id != "q_missing_answer":
                return None
            return {
                "question_id": "q_missing_answer",
                "stem": "计算：1/2 + 1/4 = ?",
                "explanation": "先通分，再相加。",
                "concept_id": "c_fraction_addition",
                "concept_name": "异分母分数加法",
                "difficulty": 0.35,
                "teaching_type": "procedure",
                "mistake_patterns": ["没有通分"],
                "rag_doc_ids": [],
                "content_availability": self.content_availability({}),
            }

        def content_availability(self, question: dict[str, object]) -> dict[str, object]:
            return {
                "status": "partial",
                "has_stem": True,
                "has_answer": False,
                "has_explanation": True,
                "missing_fields": ["standard_answer"],
                "missing_labels": ["标准答案"],
                "fallback_message": (
                    "q_missing_answer 缺少标准答案，请补齐教学内容后再用于完整练习。"
                ),
            }

    loop = MathTutorLearningLoop(
        store=InMemoryProgressStore(),
        content=MissingAnswerRepository(),
        rag=EmptyRAG(),
        context_layer=LearningContextLayer(store=InMemoryContextAssetStore()),
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-context-answer-ungraded",
            "student_id": "student-context-answer-ungraded",
            "type": "answer_submitted",
            "message": "我提交一个无法判题的答案",
            "payload": {"question_id": "q_missing_answer", "answer": "3/4"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    plan_metadata = {
        event["stage"]: event["metadata"] for event in body["teaching_trace"]
    }["plan"]
    context_assets = expert["context_assets"]

    assert body["state_summary"]["next_action"]["type"] == "record_ungraded_answer"
    task_asset = next(
        asset
        for asset in context_assets
        if asset["asset_type"] == "task_state"
        and asset["source_ref"].endswith(":answer_submitted")
    )
    assert task_asset["metadata"]["submitted_answer"] == "3/4"
    assert task_asset["metadata"]["grading_result"]["is_correct"] is None
    assert task_asset["metadata"]["grading_result"]["grading_source"] == (
        "missing_teaching_content"
    )
    assert task_asset["metadata"]["next_action"]["type"] == "record_ungraded_answer"

    tool_sources = {
        asset["source_type"]
        for asset in context_assets
        if asset["asset_type"] == "tool_observation"
    }
    assert {"kt", "rag", "mistake_diagnoser", "recommender"}.issubset(tool_sources)
    assert any(
        asset["asset_type"] == "trace_reference"
        and asset["source_ref"].endswith(":answer_submission")
        for asset in context_assets
    )
    assert any(
        asset["source_type"] == "mistake_diagnoser"
        for asset in plan_metadata["context_asset_selection"]["omitted"]
    )
    assert any(
        asset["source_type"] == "rag"
        for asset in plan_metadata["context_asset_selection"]["omitted"]
    )
    assert expert["planner_decision"]["decision"] == "record_ungraded_answer"
    assert expert["assembled_context"]["authoritative_kt_facts"] == {
        "weak_concepts": [],
        "forgetting_risks": [],
        "prediction_probability": 0.58,
        "mastery_by_concept": {},
    }
