from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.events import router as events_router
from .api.health import router as health_router
from .kt.dgekt_engine import (
    DGEKTCheckpointError,
    DGEKTConfigurationError,
    DGEKTMappingError,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="MathTutor Agent",
        version="0.1.0",
        description="Personal mathematics tutor agent with KT, RAG, memory, and TeachingTrace.",
    )
    app.include_router(events_router, prefix="/api")
    app.include_router(health_router, prefix="/api")

    @app.exception_handler(DGEKTMappingError)
    def handle_dgekt_mapping_error(
        _request: Request,
        exc: DGEKTMappingError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": f"DGEKT 映射失败：{exc}"},
        )

    @app.exception_handler(DGEKTConfigurationError)
    @app.exception_handler(DGEKTCheckpointError)
    def handle_dgekt_runtime_error(
        _request: Request,
        exc: DGEKTConfigurationError | DGEKTCheckpointError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": f"DGEKT 引擎不可用：{exc}"},
        )

    return app


app = create_app()
