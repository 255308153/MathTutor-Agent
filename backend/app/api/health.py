from fastapi import APIRouter

from . import events as events_api
from ..provider_health import build_provider_health
from ..schemas.provider_health import ProviderHealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/provider-health", response_model=ProviderHealthResponse)
def provider_health_check() -> ProviderHealthResponse:
    return build_provider_health(provider_gaps=_runtime_provider_gaps())


def _runtime_provider_gaps() -> list[dict[str, object]]:
    loop = getattr(events_api, "learning_loop", None)
    providers = [
        ("memory", getattr(loop, "memories", None)),
        ("rag", getattr(loop, "rag", None)),
    ]
    gaps: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for component, provider in providers:
        for gap in _provider_gaps(provider):
            health_gap = {"health_component": component, **gap}
            key = (
                str(health_gap.get("gap_type") or health_gap.get("category") or ""),
                str(health_gap.get("provider") or ""),
                str(health_gap.get("operation") or ""),
                str(health_gap.get("reason") or health_gap.get("message") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            gaps.append(health_gap)
    return gaps


def _provider_gaps(provider: object | None) -> list[dict[str, object]]:
    raw_gaps = getattr(provider, "last_evidence_gaps", [])
    if not isinstance(raw_gaps, list):
        return []
    return [dict(gap) for gap in raw_gaps if isinstance(gap, dict)]
