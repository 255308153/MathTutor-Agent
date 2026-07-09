from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.events import router as events_router
from .api.health import router as health_router
from .api.memories import router as memories_router
from .kt.dgekt_engine import (
    DGEKTCheckpointError,
    DGEKTConfigurationError,
    DGEKTMappingError,
    DGEKTUnsupportedTargetError,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="MathTutor Agent",
        version="0.1.0",
        description="Personal mathematics tutor agent with KT, RAG, memory, and TeachingTrace.",
    )
    app.include_router(events_router, prefix="/api")
    app.include_router(health_router, prefix="/api")
    app.include_router(memories_router, prefix="/api")

    @app.exception_handler(DGEKTMappingError)
    def handle_dgekt_mapping_error(
        _request: Request,
        exc: DGEKTMappingError,
    ) -> JSONResponse:
        code = (
            "unsupported_dgekt_target"
            if isinstance(exc, DGEKTUnsupportedTargetError)
            else "missing_mapping"
        )
        category = code
        detail = "DGEKT 目标题不受支持" if code == "unsupported_dgekt_target" else "DGEKT 映射失败"
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"{detail}：{exc}",
                "error": {
                    "code": code,
                    "category": category,
                    "stage": "diagnose",
                    "message": f"{detail}：{exc}",
                    "recoverable": True,
                    "actionable_hint": "检查 canonical mapping、ASSIST2017 question/concept id 和 Q-matrix。",
                },
            },
        )

    @app.exception_handler(DGEKTConfigurationError)
    @app.exception_handler(DGEKTCheckpointError)
    def handle_dgekt_runtime_error(
        _request: Request,
        exc: DGEKTConfigurationError | DGEKTCheckpointError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": f"DGEKT 引擎不可用：{exc}",
                "error": {
                    "code": "dgekt_runtime_unavailable",
                    "category": "scorer_failure",
                    "stage": "startup",
                    "message": f"DGEKT 引擎不可用：{exc}",
                    "recoverable": True,
                    "actionable_hint": "检查 DGEKT checkpoint、dataset_dir、Q-matrix 路径，或切回默认 mock 模式。",
                },
            },
        )

    return app


app = create_app()
