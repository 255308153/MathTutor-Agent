from fastapi import APIRouter

from ..provider_health import build_provider_health
from ..schemas.provider_health import ProviderHealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/provider-health", response_model=ProviderHealthResponse)
def provider_health_check() -> ProviderHealthResponse:
    return build_provider_health()
