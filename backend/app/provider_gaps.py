from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal


ProviderEvidenceGapType = Literal[
    "provider_failure",
    "provider_timeout",
    "provider_auth_error",
    "provider_empty_result",
    "provider_schema_mismatch",
    "provider_budget_exceeded",
]

PROVIDER_EVIDENCE_GAP_TYPES: set[str] = {
    "provider_failure",
    "provider_timeout",
    "provider_auth_error",
    "provider_empty_result",
    "provider_schema_mismatch",
    "provider_budget_exceeded",
}

RAW_PROVIDER_KEYS = {
    "raw_provider_payload",
    "sdk_response",
    "mem0_internal_id",
    "embedding_vector",
    "provider_debug",
    "vector",
    "embedding",
}


def provider_evidence_gap(
    *,
    gap_type: ProviderEvidenceGapType,
    provider: str,
    operation: str,
    reason: str,
    impact: str | None = None,
    stage: str = "load_context",
    severity: str = "warning",
    recoverable: bool = True,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "gap_type": gap_type,
        "code": gap_type,
        "category": gap_type,
        "provider": provider,
        "operation": operation,
        "stage": stage,
        "reason": reason,
        "message": reason,
        "impact": impact or _default_impact(gap_type),
        "actionable_hint": impact or _default_impact(gap_type),
        "severity": severity,
        "recoverable": recoverable,
        "recorded_at": datetime.now(UTC).isoformat(),
        "details": _sanitize(details or {}),
    }


def provider_exception_gap(
    *,
    provider: str,
    operation: str,
    exc: BaseException,
    stage: str = "load_context",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gap_type = classify_provider_exception(exc)
    return provider_evidence_gap(
        gap_type=gap_type,
        provider=provider,
        operation=operation,
        stage=stage,
        reason=f"{provider} {operation} failed: {_safe_exception_message(exc)}",
        details={
            "exception_type": exc.__class__.__name__,
            "cause_type": exc.__cause__.__class__.__name__ if exc.__cause__ else None,
            **(details or {}),
        },
    )


def classify_provider_exception(exc: BaseException) -> ProviderEvidenceGapType:
    text = " ".join(_exception_chain_messages(exc)).lower()
    type_names = " ".join(_exception_chain_type_names(exc)).lower()
    combined = f"{type_names} {text}"
    if "timeout" in combined or "timed out" in combined:
        return "provider_timeout"
    if any(token in combined for token in ("401", "403", "auth", "unauthor", "forbidden", "api key", "credential")):
        return "provider_auth_error"
    if any(token in combined for token in ("budget", "quota", "rate limit", "rate_limit", "too many requests")):
        return "provider_budget_exceeded"
    return "provider_failure"


def _default_impact(gap_type: str) -> str:
    impacts = {
        "provider_failure": "provider evidence is unavailable; local flow continues without fabricated evidence",
        "provider_timeout": "provider timed out; local flow continues without waiting for provider evidence",
        "provider_auth_error": "provider credentials were rejected or missing; no provider evidence is trusted",
        "provider_empty_result": "provider returned no evidence; no memory or citation is fabricated",
        "provider_schema_mismatch": "provider response could not be normalized; malformed evidence is discarded",
        "provider_budget_exceeded": "provider budget was exceeded; local flow continues with available evidence only",
    }
    return impacts.get(gap_type, "provider evidence gap recorded")


def _exception_chain_messages(exc: BaseException) -> list[str]:
    messages: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        messages.append(str(current))
        current = current.__cause__ or current.__context__
    return messages


def _exception_chain_type_names(exc: BaseException) -> list[str]:
    names: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        names.append(current.__class__.__name__)
        current = current.__cause__ or current.__context__
    return names


def _safe_exception_message(exc: BaseException) -> str:
    message = str(exc) or exc.__class__.__name__
    patterns = [
        (r"(?i)(api[_-]?key\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(x-api-key\s*[=:]\s*)\S+", r"\1<redacted>"),
        (r"(?i)(authorization\s*:\s*bearer\s+)\S+", r"\1<redacted>"),
        (r"(?i)(bearer\s+)\S+", r"\1<redacted>"),
        (r"(?i)(credential[s]?\s*[=:]\s*)\S+", r"\1<redacted>"),
    ]
    for pattern, replacement in patterns:
        message = re.sub(pattern, replacement, message)
    return message


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key in RAW_PROVIDER_KEYS:
                continue
            sanitized[str(key)] = _sanitize(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value
