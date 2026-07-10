from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.api import events as events_api
from backend.app.api import memories as memories_api
from backend.app.graph.learning_loop import MathTutorLearningLoop
from backend.app.memory import store as memory_mod
from backend.app.memory.sqlite_store import SqliteStudentMemoryStore
from backend.app.storage import progress_store as progress_mod
from backend.app.storage import sqlite_store as sqlite_mod
from backend.app.storage.progress_store import SqliteProgressStore
from backend.app.storage.sqlite_store import SqliteLearningStore


@pytest.fixture(autouse=True)
def isolate_v111_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test a fresh SQLite learning store and learning loop.

    V1.11 defaults to durable SQLite. Without isolation, fixed student_id values
    would leak progress across tests via data/local/mathtutor.sqlite.
    """
    store = SqliteLearningStore(tmp_path / "test-mathtutor.sqlite")
    progress = SqliteProgressStore(store)
    memories = SqliteStudentMemoryStore(store)
    monkeypatch.setattr(sqlite_mod, "_STORE", store)
    monkeypatch.setattr(progress_mod, "progress_store", progress)
    monkeypatch.setattr(memory_mod, "memory_store", memories)
    loop = MathTutorLearningLoop(
        store=progress,
        memories=memories,
        learning_store=store,
    )
    monkeypatch.setattr(events_api, "learning_loop", loop)
    # memories API falls back to module memory_store when loop is absent.
    monkeypatch.setattr(memories_api, "memory_store", memories, raising=False)
