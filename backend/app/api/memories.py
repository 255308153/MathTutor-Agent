from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..memory.store import StudentMemoryStore, memory_store
from ..schemas.memory import (
    StudentMemoryDetailResponse,
    StudentMemoryListResponse,
    public_memory_view,
)
from . import events as events_api

router = APIRouter(tags=["student-memories"])


@router.get("/students/{student_id}/memories", response_model=StudentMemoryListResponse)
def list_student_memories(
    student_id: str,
    limit: int = Query(default=25, ge=1, le=100),
) -> StudentMemoryListResponse:
    memories = [
        public_memory_view(memory)
        for memory in _active_memory_store().list_recent(student_id=student_id, limit=limit)
    ]
    return StudentMemoryListResponse(
        student_id=student_id,
        count=len(memories),
        memories=memories,
    )


@router.get(
    "/students/{student_id}/memories/{memory_id}",
    response_model=StudentMemoryDetailResponse,
)
def get_student_memory(student_id: str, memory_id: str) -> StudentMemoryDetailResponse:
    memory = _active_memory_store().get(student_id=student_id, memory_id=memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="学生记忆不存在")
    return StudentMemoryDetailResponse(
        student_id=student_id,
        memory=public_memory_view(memory),
    )


def _active_memory_store() -> StudentMemoryStore:
    loop_memory_store = getattr(getattr(events_api, "learning_loop", None), "memories", None)
    return loop_memory_store or memory_store
