from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query

from ..memory.store import MemoryProviderOperationError, StudentMemoryStore, memory_store
from ..provider_gaps import provider_exception_gap
from ..schemas.memory import (
    StudentMemoryControlRequest,
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
    store = _active_memory_store()
    try:
        store_memories = store.list_recent(student_id=student_id, limit=limit)
    except Exception as exc:
        _raise_provider_operation_error(store, operation="list_recent", exc=exc)
    _raise_if_provider_failed(store)
    memories = [
        public_memory_view(memory)
        for memory in store_memories
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
    store = _active_memory_store()
    try:
        memory = store.get(student_id=student_id, memory_id=memory_id)
    except Exception as exc:
        _raise_provider_operation_error(store, operation="get", exc=exc)
    _raise_if_provider_failed(store)
    if memory is None:
        raise HTTPException(status_code=404, detail="学生记忆不存在")
    return StudentMemoryDetailResponse(
        student_id=student_id,
        memory=public_memory_view(memory),
    )


@router.post(
    "/students/{student_id}/memories/{memory_id}/disable",
    response_model=StudentMemoryDetailResponse,
)
def disable_student_memory(
    student_id: str,
    memory_id: str,
    request: StudentMemoryControlRequest | None = Body(default=None),
) -> StudentMemoryDetailResponse:
    payload = request or StudentMemoryControlRequest()
    store = _active_memory_store()
    try:
        memory = store.disable(
            student_id=student_id,
            memory_id=memory_id,
            actor=payload.actor,
            reason=payload.reason,
        )
    except Exception as exc:
        _raise_provider_operation_error(store, operation="memory_control", exc=exc)
    _raise_if_provider_failed(store)
    if memory is None:
        raise HTTPException(status_code=404, detail="学生记忆不存在")
    return StudentMemoryDetailResponse(
        student_id=student_id,
        memory=public_memory_view(memory),
    )


@router.post(
    "/students/{student_id}/memories/{memory_id}/enable",
    response_model=StudentMemoryDetailResponse,
)
def enable_student_memory(
    student_id: str,
    memory_id: str,
    request: StudentMemoryControlRequest | None = Body(default=None),
) -> StudentMemoryDetailResponse:
    payload = request or StudentMemoryControlRequest()
    store = _active_memory_store()
    try:
        memory = store.enable(
            student_id=student_id,
            memory_id=memory_id,
            actor=payload.actor,
            reason=payload.reason,
        )
    except Exception as exc:
        _raise_provider_operation_error(store, operation="memory_control", exc=exc)
    _raise_if_provider_failed(store)
    if memory is None:
        raise HTTPException(status_code=404, detail="学生记忆不存在")
    return StudentMemoryDetailResponse(
        student_id=student_id,
        memory=public_memory_view(memory),
    )


@router.delete(
    "/students/{student_id}/memories/{memory_id}",
    response_model=StudentMemoryDetailResponse,
)
def delete_student_memory(
    student_id: str,
    memory_id: str,
    request: StudentMemoryControlRequest | None = Body(default=None),
) -> StudentMemoryDetailResponse:
    payload = request or StudentMemoryControlRequest()
    store = _active_memory_store()
    try:
        memory = store.delete(
            student_id=student_id,
            memory_id=memory_id,
            actor=payload.actor,
            reason=payload.reason,
        )
    except Exception as exc:
        _raise_provider_operation_error(store, operation="memory_delete", exc=exc)
    _raise_if_provider_failed(store)
    if memory is None:
        raise HTTPException(status_code=404, detail="学生记忆不存在")
    return StudentMemoryDetailResponse(
        student_id=student_id,
        memory=public_memory_view(memory),
    )


def _active_memory_store() -> StudentMemoryStore:
    loop_memory_store = getattr(getattr(events_api, "learning_loop", None), "memories", None)
    return loop_memory_store or memory_store


def _raise_provider_operation_error(
    store: StudentMemoryStore,
    *,
    operation: str,
    exc: Exception,
) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, MemoryProviderOperationError):
        gap = exc.gap
    else:
        gap = provider_exception_gap(
            provider=_provider_name(store),
            operation=operation,
            exc=exc,
        )
    raise HTTPException(status_code=503, detail=_public_provider_error(gap)) from exc


def _raise_if_provider_failed(store: StudentMemoryStore) -> None:
    gap = getattr(store, "last_error", None)
    if isinstance(gap, dict):
        raise HTTPException(status_code=503, detail=_public_provider_error(gap))


def _public_provider_error(gap: dict[str, object]) -> dict[str, object]:
    return {
        "code": gap.get("code") or gap.get("gap_type") or "provider_failure",
        "category": gap.get("category") or gap.get("gap_type") or "provider_failure",
        "provider": gap.get("provider") or "memory_provider",
        "operation": gap.get("operation") or "memory_operation",
        "message": gap.get("message") or gap.get("reason") or "记忆 provider 操作失败。",
        "recoverable": gap.get("recoverable", True),
        "actionable_hint": gap.get("actionable_hint")
        or "请稍后重试；默认学习流程会继续使用可用的本地证据。",
    }


def _provider_name(store: StudentMemoryStore) -> str:
    provider_mode = getattr(store, "provider_mode", None)
    source = getattr(store, "source", None)
    return str(source or provider_mode or "memory_provider")
