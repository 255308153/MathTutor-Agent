from fastapi import FastAPI

from .api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="MathTutor Agent",
        version="0.1.0",
        description="Personal mathematics tutor agent with KT, RAG, memory, and TeachingTrace.",
    )
    app.include_router(health_router, prefix="/api")
    return app


app = create_app()
