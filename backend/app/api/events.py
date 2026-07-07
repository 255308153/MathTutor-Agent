from __future__ import annotations

from fastapi import APIRouter

from ..graph.learning_loop import learning_loop
from ..schemas.learning import LearningEvent, MathTutorEventResponse

router = APIRouter(tags=["learning-events"])


@router.post("/events", response_model=MathTutorEventResponse)
def handle_learning_event(event: LearningEvent) -> MathTutorEventResponse:
    return learning_loop.handle_event(event)
