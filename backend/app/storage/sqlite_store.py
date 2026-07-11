from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4
from urllib.parse import unquote, urlparse

from ..core.config import MathTutorSettings, get_settings
from ..memory.store import (
    StudentMemory,
    memory_dedupe_key,
)
from ..schemas.learning import KTLearningProgress
from ..schemas.readiness import TrialFeedbackCreate, TrialFeedbackRecord


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "data" / "local" / "mathtutor.sqlite"


def resolve_sqlite_path(db_url: str | None = None) -> Path:
    raw = (db_url or get_settings().db_url or "").strip()
    if not raw:
        return DEFAULT_SQLITE_PATH
    if raw == ":memory:" or raw.startswith("file::memory:"):
        return Path(":memory:")
    if raw.startswith("sqlite:///"):
        path_text = unquote(raw[len("sqlite:///") :])
    elif raw.startswith("sqlite://"):
        parsed = urlparse(raw)
        path_text = unquote(parsed.path or "")
    else:
        path_text = raw
    path = Path(path_text)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


class SqliteLearningStore:
    """Durable local store for progress, traces, memories, probes, and trial feedback.

    This store never recomputes KT/DGEKT mastery. It only persists domain snapshots
    and audit references written by the learning loop or control APIs.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            self.db_path = resolve_sqlite_path()
        elif str(db_path) == ":memory:":
            self.db_path = Path(":memory:")
        else:
            self.db_path = Path(db_path)
        self._lock = Lock()
        self._memory_conn: sqlite3.Connection | None = None
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        if self.db_path == Path(":memory:"):
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS learning_progress (
                        student_id TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS teaching_traces (
                        trace_id TEXT PRIMARY KEY,
                        student_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_traces_student_session
                        ON teaching_traces(student_id, session_id, created_at);
                    CREATE TABLE IF NOT EXISTS student_memories (
                        memory_id TEXT PRIMARY KEY,
                        student_id TEXT NOT NULL,
                        dedupe_key TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_memories_student
                        ON student_memories(student_id, updated_at);
                    CREATE TABLE IF NOT EXISTS probe_results (
                        probe_id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS trial_feedback (
                        feedback_id TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS store_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    "INSERT OR REPLACE INTO store_meta(key, value) VALUES(?, ?)",
                    ("schema_version", "v1.11"),
                )
                conn.commit()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()

    def health_check(self) -> dict[str, Any]:
        try:
            with self._lock:
                conn = self._connect()
                try:
                    row = conn.execute(
                        "SELECT value FROM store_meta WHERE key = ?",
                        ("schema_version",),
                    ).fetchone()
                    progress_count = conn.execute(
                        "SELECT COUNT(*) AS c FROM learning_progress"
                    ).fetchone()["c"]
                    trace_count = conn.execute(
                        "SELECT COUNT(*) AS c FROM teaching_traces"
                    ).fetchone()["c"]
                    memory_count = conn.execute(
                        "SELECT COUNT(*) AS c FROM student_memories WHERE status != 'deleted'"
                    ).fetchone()["c"]
                finally:
                    if self.db_path != Path(":memory:"):
                        conn.close()
            return {
                "available": True,
                "backend": "sqlite",
                "schema_version": row["value"] if row else "unknown",
                "progress_count": int(progress_count),
                "trace_count": int(trace_count),
                "memory_count": int(memory_count),
                "path_category": "local_sqlite" if self.db_path != Path(":memory:") else "memory",
            }
        except Exception as exc:  # noqa: BLE001 - readiness must stay resilient
            return {
                "available": False,
                "backend": "sqlite",
                "error_category": type(exc).__name__,
                "reason": "持久化存储当前不可用。",
            }

    # --- progress ---
    def get_progress(self, student_id: str) -> KTLearningProgress | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT payload_json FROM learning_progress WHERE student_id = ?",
                    (student_id,),
                ).fetchone()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()
        if row is None:
            return None
        return KTLearningProgress.model_validate_json(row["payload_json"])

    def save_progress(self, progress: KTLearningProgress) -> KTLearningProgress:
        payload = progress.model_dump(mode="json")
        now = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO learning_progress(student_id, payload_json, updated_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(student_id) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at
                    """,
                    (progress.student_id, json.dumps(payload, ensure_ascii=False), now),
                )
                conn.commit()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()
        return deepcopy(progress)

    # --- teaching traces ---
    def save_trace(
        self,
        *,
        trace_id: str,
        student_id: str,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO teaching_traces(
                        trace_id, student_id, session_id, event_type, payload_json, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trace_id) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        created_at = excluded.created_at
                    """,
                    (
                        trace_id,
                        student_id,
                        session_id,
                        event_type,
                        json.dumps(payload, ensure_ascii=False),
                        now,
                    ),
                )
                conn.commit()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()

    def list_trace_summaries(
        self,
        student_id: str,
        session_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT payload_json, created_at FROM teaching_traces "
            "WHERE student_id = ?"
        )
        params: list[Any] = [student_id]
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(query, params).fetchall()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()
        summaries: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            summary = payload.get("summary") or {}
            summaries.append(
                {
                    "trace_id": payload.get("trace_id"),
                    "session_id": payload.get("session_id"),
                    "student_id": payload.get("student_id"),
                    "intent": summary.get("intent") or payload.get("intent"),
                    "stages": summary.get("stages") or [],
                    "student_explanation": summary.get("student_explanation") or "",
                    "progress_version": payload.get("progress_version"),
                    "created_at": row["created_at"],
                    "recommendation_basis": payload.get("recommendation_basis") or [],
                }
            )
        return summaries

    # --- memories ---
    def list_memories(self, student_id: str, *, include_deleted: bool = False) -> list[StudentMemory]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT payload_json FROM student_memories
                    WHERE student_id = ?
                    ORDER BY updated_at DESC
                    """,
                    (student_id,),
                ).fetchall()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()
        memories: list[StudentMemory] = []
        for row in rows:
            memory = StudentMemory.model_validate_json(row["payload_json"])
            if not include_deleted and memory.status == "deleted":
                continue
            memories.append(memory)
        return memories

    def get_memory(self, student_id: str, memory_id: str) -> StudentMemory | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT payload_json FROM student_memories
                    WHERE student_id = ? AND memory_id = ?
                    """,
                    (student_id, memory_id),
                ).fetchone()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()
        if row is None:
            return None
        memory = StudentMemory.model_validate_json(row["payload_json"])
        if memory.status == "deleted":
            return None
        return memory

    def write_memory(self, memory: StudentMemory) -> StudentMemory:
        memories = self.list_memories(memory.student_id, include_deleted=True)
        now = datetime.now(UTC).isoformat()
        dedupe = memory_dedupe_key(memory)
        for existing in memories:
            if existing.status == "deleted":
                continue
            if memory_dedupe_key(existing) == dedupe:
                merged = existing.model_copy(
                    update={
                        "evidence": {**existing.evidence, **memory.evidence},
                        "provenance": {**existing.provenance, **memory.provenance},
                        "updated_at": now,
                        "freshness": "fresh",
                        "source": existing.source or "local_fallback",
                    }
                )
                self._upsert_memory(merged, dedupe_key=dedupe)
                return merged
        stored = memory.model_copy(update={"source": memory.source or "local_fallback"})
        self._upsert_memory(stored, dedupe_key=dedupe)
        return stored

    def update_memory(self, memory: StudentMemory) -> StudentMemory:
        self._upsert_memory(memory, dedupe_key=memory_dedupe_key(memory))
        return memory

    def _upsert_memory(self, memory: StudentMemory, *, dedupe_key: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO student_memories(
                        memory_id, student_id, dedupe_key, payload_json, status, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(memory_id) DO UPDATE SET
                        student_id = excluded.student_id,
                        dedupe_key = excluded.dedupe_key,
                        payload_json = excluded.payload_json,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        memory.memory_id,
                        memory.student_id,
                        dedupe_key,
                        memory.model_dump_json(),
                        memory.status,
                        memory.updated_at,
                    ),
                )
                conn.commit()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()

    # --- probes ---
    def save_probe_result(self, provider: str, payload: dict[str, Any]) -> str:
        probe_id = f"probe-{uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()
        body = {**payload, "probe_id": probe_id, "provider": provider, "created_at": now}
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO probe_results(probe_id, provider, payload_json, created_at)
                    VALUES(?, ?, ?, ?)
                    """,
                    (probe_id, provider, json.dumps(body, ensure_ascii=False), now),
                )
                conn.commit()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()
        return probe_id

    def latest_probe_results(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT payload_json FROM probe_results
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()
        return [json.loads(row["payload_json"]) for row in rows]

    # --- trial feedback ---
    def save_trial_feedback(self, request: TrialFeedbackCreate) -> TrialFeedbackRecord:
        now = datetime.now(UTC).isoformat()
        record = TrialFeedbackRecord(
            feedback_id=f"tfb-{uuid4().hex[:12]}",
            student_flow=request.student_flow,
            issue_category=request.issue_category,
            impact=request.impact,
            handling_status=request.handling_status,
            residual_risk=request.residual_risk,
            decision=request.decision,
            operator_note=request.operator_note,
            recorded_at=now,
            actor=request.actor or "operator",
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO trial_feedback(feedback_id, payload_json, created_at)
                    VALUES(?, ?, ?)
                    """,
                    (record.feedback_id, record.model_dump_json(), now),
                )
                conn.commit()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()
        return record

    def list_trial_feedback(self, limit: int = 20) -> list[TrialFeedbackRecord]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT payload_json FROM trial_feedback
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            finally:
                if self.db_path != Path(":memory:"):
                    conn.close()
        return [TrialFeedbackRecord.model_validate_json(row["payload_json"]) for row in rows]


_STORE: SqliteLearningStore | None = None
_STORE_LOCK = Lock()


def get_learning_store(settings: MathTutorSettings | None = None) -> SqliteLearningStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            active = settings or get_settings()
            _STORE = SqliteLearningStore(resolve_sqlite_path(active.db_url))
        return _STORE


def reset_learning_store_for_tests(store: SqliteLearningStore | None = None) -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = store
