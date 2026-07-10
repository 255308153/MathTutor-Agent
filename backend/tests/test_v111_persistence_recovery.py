from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.main import create_app
from backend.app.memory.sqlite_store import SqliteStudentMemoryStore
from backend.app.memory.store import StudentMemory
from backend.app.schemas.learning import LearningEvent
from backend.app.storage.content_repository import content_repository
from backend.app.storage.progress_store import SqliteProgressStore
from backend.app.storage.sqlite_store import SqliteLearningStore


SCRATCH = Path(
    "/var/folders/fd/p49ht4h53p9f30pmqm84t1p80000gp/T/grok-goal-f3abcd2e3523/implementer"
)


def test_continuous_learning_persists_across_new_loop_instance(tmp_path: Path) -> None:
    db_path = tmp_path / "learning.sqlite"
    store = SqliteLearningStore(db_path)
    progress_store = SqliteProgressStore(store)
    memory_store = SqliteStudentMemoryStore(store)

    student_id = "student-v111-persist"
    session_id = "session-v111-persist"

    loop_a = MathTutorLearningLoop(
        store=progress_store,
        memories=memory_store,
        learning_store=store,
    )
    first = loop_a.handle_event(
        LearningEvent(
            session_id=session_id,
            student_id=student_id,
            type="chat_message",
            message="我下一步应该练什么？",
            payload={},
        )
    )
    question = first.recommended_questions[0]
    standard = content_repository.get_question(question["question_id"])["standard_answer"]
    graded = loop_a.handle_event(
        LearningEvent(
            session_id=session_id,
            student_id=student_id,
            type="answer_submitted",
            message="提交正确答案",
            payload={"question_id": question["question_id"], "answer": standard},
        )
    )
    version_before = graded.state_summary["progress_version"]
    assert version_before >= 1
    assert graded.teaching_trace_summary.stages

    # Simulate process restart with a fresh loop on the same SQLite file.
    store_b = SqliteLearningStore(db_path)
    loop_b = MathTutorLearningLoop(
        store=SqliteProgressStore(store_b),
        memories=SqliteStudentMemoryStore(store_b),
        learning_store=store_b,
    )
    recovered_progress = loop_b.store.get_or_create(student_id)
    assert recovered_progress.version == version_before
    assert recovered_progress.concept_states

    traces = store_b.list_trace_summaries(student_id, session_id=session_id, limit=5)
    assert traces
    assert traces[0]["trace_id"]
    assert traces[0]["recommendation_basis"] or recovered_progress.recommendation_history

    # Duplicate graded event must not bump mastery version again.
    dup = loop_b.handle_event(
        LearningEvent(
            session_id=session_id,
            student_id=student_id,
            type="answer_submitted",
            message="重复提交",
            payload={"question_id": question["question_id"], "answer": standard},
        )
    )
    assert "重复提交" in dup.response
    assert dup.state_summary["progress_version"] == version_before

    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "persist-recovery.log").write_text(
        "\n".join(
            [
                f"version_before={version_before}",
                f"recovered_version={recovered_progress.version}",
                f"trace_count={len(traces)}",
                f"duplicate_version={dup.state_summary['progress_version']}",
                f"first_trace={traces[0]['trace_id']}",
            ]
        ),
        encoding="utf-8",
    )


def test_session_recovery_api_returns_trace_summary(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "api-recovery.sqlite"
    store = SqliteLearningStore(db_path)
    from backend.app.storage import sqlite_store as sqlite_mod
    from backend.app.api import events as events_api

    monkeypatch.setattr(sqlite_mod, "_STORE", store)
    progress_store = SqliteProgressStore(store)
    loop = MathTutorLearningLoop(
        store=progress_store,
        memories=SqliteStudentMemoryStore(store),
        learning_store=store,
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)

    client = TestClient(create_app())
    student_id = "student-api-recovery"
    session_id = "session-api-recovery"
    turn = client.post(
        "/api/events",
        json={
            "session_id": session_id,
            "student_id": student_id,
            "type": "chat_message",
            "message": "我下一步应该练什么？",
            "payload": {},
        },
    )
    assert turn.status_code == 200

    recovery = client.get(f"/api/students/{student_id}/sessions/{session_id}/recovery")
    assert recovery.status_code == 200
    body = recovery.json()
    assert body["recovered"] is True
    assert body["progress_version"] >= 0
    assert body["recent_trace_summaries"]


def test_memory_control_survives_restart_and_excludes_from_search(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite"
    store = SqliteLearningStore(db_path)
    memories = SqliteStudentMemoryStore(store)
    student_id = "student-memory-durable"

    written = memories.write(
        StudentMemory(
            student_id=student_id,
            memory_type="preference",
            content="学生偏好先看分数步骤拆解。",
            evidence={"preferred_teaching_type": "procedure"},
        )
    )
    disabled = memories.disable(student_id, written.memory_id, actor="student")
    assert disabled is not None
    assert disabled.status == "disabled"

    # Restart store
    store_b = SqliteLearningStore(db_path)
    memories_b = SqliteStudentMemoryStore(store_b)
    listed = memories_b.list_recent(student_id)
    assert any(item.memory_id == written.memory_id and item.status == "disabled" for item in listed)
    searched = memories_b.search(student_id, query="分数 步骤", limit=5)
    assert all(item.memory_id != written.memory_id for item in searched)

    deleted = memories_b.delete(student_id, written.memory_id, actor="student")
    assert deleted is not None
    assert deleted.status == "deleted"

    store_c = SqliteLearningStore(db_path)
    memories_c = SqliteStudentMemoryStore(store_c)
    assert memories_c.get(student_id, written.memory_id) is None
    assert all(item.memory_id != written.memory_id for item in memories_c.list_recent(student_id))
    assert all(item.memory_id != written.memory_id for item in memories_c.search(student_id, "分数"))

    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "memory-control.log").write_text(
        "disabled_excluded_from_search=true\ndeleted_absent_after_restart=true\n",
        encoding="utf-8",
    )
