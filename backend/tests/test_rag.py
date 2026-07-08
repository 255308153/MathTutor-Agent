from fastapi.testclient import TestClient

from backend.app.api import events as events_api
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.main import create_app
from backend.app.rag.knowledge_rag import LocalKnowledgeRAG
from backend.app.rag.schema import RAGDocument
from backend.app.storage.progress_store import InMemoryProgressStore


def test_rag_document_schema_accepts_canonical_metadata() -> None:
    document = RAGDocument.model_validate(
        {
            "doc_id": "rag-schema-test",
            "doc_type": "question_explanation",
            "title": "q_frac_001 题解",
            "content": "先通分再相加。",
            "source": "demo-rag/question_solutions.md#q_frac_001",
            "concept_id": "c_fraction_addition",
            "question_id": "q_frac_001",
            "assist2017_question_id": 3,
            "assist2017_concept_id": 2,
            "canonical_mapping": {
                "question_id": "q_frac_001",
                "assist2017_question_id": 3,
                "q_matrix_reference": {"row_index": 3},
            },
            "provenance": {"mapping_source": "fixture"},
            "coverage": {"coverage_type": "question", "question_aligned": True},
            "keywords": ["通分"],
        }
    )

    assert document.assist2017_question_id == 3
    assert document.coverage["coverage_type"] == "question"


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
    assert results[0].assist2017_question_id == 3
    assert results[0].assist2017_concept_id == 2
    assert results[0].coverage["coverage_type"] == "question"
    assert results[0].canonical_mapping["q_matrix_reference"]["concept_column_indices"] == [2]


def test_local_rag_filters_by_assist2017_ids() -> None:
    rag = LocalKnowledgeRAG()

    results = rag.search(
        query="通分 题解",
        filters={
            "doc_type": "question_explanation",
            "assist2017_question_id": 3,
            "assist2017_concept_id": 2,
        },
        limit=3,
    )

    assert [result.doc_id for result in results] == ["rag_q_frac_001_solution"]
    assert results[0].question_id == "q_frac_001"


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
    assert body["teaching_trace_summary"]["expert_evidence"]["rag_sources"][0]["concept_id"] == (
        "c_fraction_addition"
    )


def test_answer_submission_rag_citation_matches_canonical_question_and_concept() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-rag-canonical-001",
            "student_id": "student-rag-canonical-001",
            "type": "answer_submitted",
            "message": "我选 1/6",
            "payload": {
                "question_id": "q_frac_001",
                "answer": "1/6",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    sources = body["teaching_trace_summary"]["expert_evidence"]["rag_sources"]
    question_sources = [source for source in sources if source["question_id"] == "q_frac_001"]

    assert question_sources
    assert question_sources[0]["assist2017_question_id"] == 3
    assert question_sources[0]["assist2017_concept_id"] == 2
    assert question_sources[0]["coverage"]["question_aligned"] is True
    assert body["state_summary"]["weak_concepts"][0]["concept_id"] == "c_fraction_addition"
    assert all(
        source["concept_id"] in (None, "c_fraction_addition")
        for source in sources
    )
    assert "demo-rag/" in body["response"]


def test_missing_rag_citation_reports_gap_without_overwriting_kt(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        events_api,
        "learning_loop",
        MathTutorLearningLoop(
            store=InMemoryProgressStore(),
            rag=EmptyKnowledgeRAG(),
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/events",
        json={
            "session_id": "session-rag-gap-001",
            "student_id": "student-rag-gap-001",
            "type": "answer_submitted",
            "message": "我选 1/6",
            "payload": {
                "question_id": "q_frac_001",
                "answer": "1/6",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    expert = body["teaching_trace_summary"]["expert_evidence"]
    gaps = expert["assembled_context"]["evidence_gaps"]

    assert expert["rag_sources"] == []
    assert any(gap["reason"] == "RAG 未找到相关知识资源" for gap in gaps)
    assert expert["kt_diagnosis"]["weak_concepts"][0]["concept_id"] == "c_fraction_addition"
    assert expert["kt_diagnosis"]["prediction_probability"] == 0.58


class EmptyKnowledgeRAG:
    def search(
        self,
        query: str,
        filters: dict | None = None,
        limit: int = 3,
    ) -> list:
        return []
