from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.rag.knowledge_rag import LocalKnowledgeRAG


def test_local_rag_filters_by_doc_type_concept_and_returns_source() -> None:
    rag = LocalKnowledgeRAG()

    results = rag.search(
        query="通分 错因",
        filters={
            "doc_type": "mistake_pattern",
            "concept_id": "c_fraction_addition",
            "question_id": "q_frac_001",
        },
        limit=3,
    )

    assert [result.doc_id for result in results] == ["rag_fraction_addition_mistake"]
    assert results[0].source == "demo-rag/fraction_mistakes.md"
    assert results[0].doc_type == "mistake_pattern"


def test_local_rag_can_retrieve_learning_strategy() -> None:
    rag = LocalKnowledgeRAG()

    results = rag.search(
        query="推荐 薄弱 遗忘风险",
        filters={"doc_type": "learning_strategy"},
        limit=2,
    )

    assert results[0].doc_type == "learning_strategy"
    assert "source" in results[0].model_dump()


def test_knowledge_question_returns_rag_citation_without_changing_kt_facts() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-rag-001",
            "student_id": "student-rag-001",
            "type": "chat_message",
            "message": "分数加法为什么要先通分？",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "参考：" in body["response"]
    assert "demo-rag/" in body["response"]
    assert body["state_summary"]["weak_concepts"] == []
    load_trace = body["teaching_trace"][0]
    assert load_trace["stage"] == "load_context"
    assert load_trace["metadata"]["rag_query"] == "分数加法为什么要先通分？"
    assert load_trace["metadata"]["rag_sources"]
