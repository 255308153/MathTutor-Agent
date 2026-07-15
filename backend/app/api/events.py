from __future__ import annotations

from fastapi import APIRouter

from ..graph.learning_loop import learning_loop
from ..runtime.agent_runtime import MathTutorAgentRuntime
from ..schemas.learning import LearningEvent, MathTutorEventResponse

router = APIRouter(tags=["learning-events"])


@router.post("/events", response_model=MathTutorEventResponse)
def handle_learning_event(event: LearningEvent) -> MathTutorEventResponse:
    return MathTutorAgentRuntime(learning_loop=learning_loop).handle_event(event)
