from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..core.config import MathTutorSettings, get_settings
from ..schemas.readiness import TrialProbeSummary
from ..storage.sqlite_store import SqliteLearningStore, get_learning_store


def run_canary_probes(
    *,
    providers: list[str] | None = None,
    canary_token: str = "mathtutor-canary",
    settings: MathTutorSettings | None = None,
    store: SqliteLearningStore | None = None,
) -> list[TrialProbeSummary]:
    """Run explicit opt-in canary probes. Default environments skip safely.

    Probes never use student content and never write learning facts.
    """
    active = settings or get_settings()
    learning_store = store or get_learning_store(active)
    selected = providers or ["memory", "rag"]
    results: list[TrialProbeSummary] = []

    if not active.enable_provider_canary_probe:
        for provider in selected:
            summary = TrialProbeSummary(
                provider=provider,
                mode="opt_in_disabled",
                status="skipped",
                recoverable=True,
                reason="未启用 canary probe（MATHTUTOR_ENABLE_PROVIDER_CANARY_PROBE=false）。",
                actionable_hint="仅在受控运维环境显式开启 canary probe，并提供隔离 canary 条件。",
                probed_at=None,
                skipped=True,
            )
            results.append(summary)
        return results

    for provider in selected:
        if provider == "memory":
            summary = _probe_memory(active, canary_token=canary_token)
        elif provider == "rag":
            summary = _probe_rag(active, canary_token=canary_token)
        else:
            summary = TrialProbeSummary(
                provider=provider,
                mode="unsupported",
                status="not_ready",
                recoverable=True,
                reason=f"不支持的 probe 目标：{provider}。",
                actionable_hint="仅支持 memory 与 rag canary probe。",
                probed_at=datetime.now(UTC).isoformat(),
                skipped=False,
            )
        learning_store.save_probe_result(
            provider=summary.provider,
            payload=summary.model_dump(mode="json"),
        )
        results.append(summary)
    return results


def latest_probe_summaries(
    store: SqliteLearningStore | None = None,
    limit: int = 6,
) -> list[TrialProbeSummary]:
    learning_store = store or get_learning_store()
    summaries: list[TrialProbeSummary] = []
    for item in learning_store.latest_probe_results(limit=limit):
        try:
            summaries.append(
                TrialProbeSummary(
                    provider=str(item.get("provider") or "unknown"),
                    mode=str(item.get("mode") or "unknown"),
                    status=item.get("status") or "skipped",  # type: ignore[arg-type]
                    recoverable=bool(item.get("recoverable", True)),
                    reason=str(item.get("reason") or ""),
                    actionable_hint=str(item.get("actionable_hint") or ""),
                    probed_at=item.get("probed_at") or item.get("created_at"),
                    skipped=bool(item.get("skipped", False)),
                )
            )
        except Exception:  # noqa: BLE001
            continue
    return summaries


def _probe_memory(settings: MathTutorSettings, *, canary_token: str) -> TrialProbeSummary:
    now = datetime.now(UTC).isoformat()
    if settings.memory_provider_mode != "live_provider":
        return TrialProbeSummary(
            provider="memory",
            mode=settings.memory_provider_mode,
            status="skipped",
            recoverable=True,
            reason="Memory 当前不是 live_provider，已安全跳过 canary probe。",
            actionable_hint="仅在 MATHTUTOR_MEMORY_PROVIDER_MODE=live_provider 且凭据完备时执行真实 probe。",
            probed_at=now,
            skipped=True,
        )
    if not settings.mem0_api_key:
        return TrialProbeSummary(
            provider="memory",
            mode="live_provider",
            status="not_ready",
            recoverable=True,
            reason="Mem0 canary probe 缺少 MATHTUTOR_MEM0_API_KEY。",
            actionable_hint="在本地 env 补齐凭据后重试；不要把 key 提交到 Git。",
            probed_at=now,
            skipped=False,
        )
    if not settings.run_mem0_live_smoke:
        return TrialProbeSummary(
            provider="memory",
            mode="live_provider",
            status="skipped",
            recoverable=True,
            reason="Mem0 live smoke 未显式开启（MATHTUTOR_RUN_MEM0_LIVE_SMOKE=false）。",
            actionable_hint="仅在运维窗口显式开启 live smoke，并使用隔离 canary token。",
            probed_at=now,
            skipped=True,
        )
    # Controlled canary: no network call unless both flags and key exist.
    # We still avoid real network access in default CI; mark configuration-ready only.
    return TrialProbeSummary(
        provider="memory",
        mode="live_provider",
        status="degraded",
        recoverable=True,
        reason=(
            f"Mem0 canary 配置已就绪（token={_sanitize_token(canary_token)}），"
            "但默认实现不发起真实网络调用，避免无预算 live 访问。"
        ),
        actionable_hint="在隔离环境确认 endpoint/quota 后，由运维执行真实 smoke 并回写 probe 结果。",
        probed_at=now,
        skipped=False,
    )


def _probe_rag(settings: MathTutorSettings, *, canary_token: str) -> TrialProbeSummary:
    now = datetime.now(UTC).isoformat()
    if settings.rag_provider_mode != "live_provider":
        return TrialProbeSummary(
            provider="rag",
            mode=settings.rag_provider_mode,
            status="skipped",
            recoverable=True,
            reason="RAG 当前不是 live_provider，已安全跳过 canary probe。",
            actionable_hint="仅在 MATHTUTOR_RAG_PROVIDER_MODE=live_provider 且配置完备时执行真实 probe。",
            probed_at=now,
            skipped=True,
        )
    missing: list[str] = []
    if not settings.rag_provider_endpoint:
        missing.append("MATHTUTOR_RAG_PROVIDER_ENDPOINT")
    if not settings.rag_provider_collection:
        missing.append("MATHTUTOR_RAG_PROVIDER_COLLECTION")
    api_key = (
        settings.openviking_api_key
        if settings.rag_live_provider == "openviking"
        else settings.vikingdb_api_key
    )
    if not api_key:
        missing.append(
            "MATHTUTOR_OPENVIKING_API_KEY"
            if settings.rag_live_provider == "openviking"
            else "MATHTUTOR_VIKINGDB_API_KEY"
        )
    if missing:
        return TrialProbeSummary(
            provider="rag",
            mode="live_provider",
            status="not_ready",
            recoverable=True,
            reason=f"RAG canary probe 缺少 {'、'.join(missing)}。",
            actionable_hint="补齐 endpoint/collection/API key 后重试；凭据仅保存在本地 env。",
            probed_at=now,
            skipped=False,
        )
    if not settings.run_viking_rag_smoke:
        return TrialProbeSummary(
            provider="rag",
            mode="live_provider",
            status="skipped",
            recoverable=True,
            reason="RAG live smoke 未显式开启（MATHTUTOR_RUN_VIKING_RAG_SMOKE=false）。",
            actionable_hint="仅在运维窗口显式开启 live smoke，并使用隔离 canary query。",
            probed_at=now,
            skipped=True,
        )
    return TrialProbeSummary(
        provider="rag",
        mode="live_provider",
        status="degraded",
        recoverable=True,
        reason=(
            f"RAG canary 配置已就绪（token={_sanitize_token(canary_token)}），"
            "但默认实现不发起真实网络调用，避免无预算 live 访问。"
        ),
        actionable_hint="在隔离环境确认 collection/quota 后，由运维执行真实 smoke 并回写 probe 结果。",
        probed_at=now,
        skipped=False,
    )


def _sanitize_token(token: str) -> str:
    text = (token or "").strip()
    if not text:
        return "empty"
    if len(text) <= 8:
        return text
    return f"{text[:4]}…{text[-2:]}"


def sanitize_probe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop secrets, paths, raw payloads, and student content from probe output."""
    forbidden_keys = {
        "api_key",
        "authorization",
        "raw_provider_payload",
        "sdk_response",
        "embedding",
        "embedding_vector",
        "path",
        "checkpoint_path",
        "student_content",
        "message",
        "answer",
    }
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in forbidden_keys:
            continue
        if isinstance(value, str) and any(
            marker in value.lower()
            for marker in ("/users/", "api_key", "bearer ", ".pt", ".ckpt")
        ):
            continue
        cleaned[key] = value
    return cleaned
