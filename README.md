# MathTutor Agent

MathTutor Agent is a personal mathematics tutor agent based on explainable knowledge tracing, retrieval-augmented generation, and long-term student memory.

V1 focuses on one learner, one subject, and one clear learning loop:

```text
Learning event / student question
-> student state and memory retrieval
-> math RAG retrieval
-> knowledge tracing diagnosis
-> teaching action planning
-> recommendation / explanation / review
-> student-facing response
-> TeachingTrace + memory update
```

## V1 Scope

- Math-only personal tutor agent.
- ASSISTments2017 / local DGEKT data as the first dataset base.
- LangGraph-style orchestration.
- Mem0-style student memory.
- VikingDB adapter with a local Chroma fallback.
- Mock KT engine first, DGEKT/SAFKT engine behind a stable interface later.
- Risk-prioritized mastery path.
- TeachingTrace for inspectable agent execution.

## Repository Layout

```text
backend/
  app/
    api/        FastAPI routers
    core/       config, events, trace primitives
    graph/      LangGraph orchestration
    kt/         KTStateEngine interface and implementations
    memory/     student memory store and refinery
    rag/        knowledge retrieval adapters
    planning/   teaching planner and recommender
    schemas/    Pydantic domain schemas
    storage/    database repositories

frontend/       learning dashboard
data/           local dataset, RAG docs, teaching content maps
docs/           architecture and design notes
```

## First Development Milestones

1. Build the FastAPI + LangGraph skeleton.
2. Define `MathTutorState`, `KTLearningProgress`, and event schemas.
3. Implement `MockKTStateEngine`.
4. Add a small teaching content map and RAG document set.
5. Implement TeachingTrace events.
6. Build the first learning dashboard.

See [docs/V1_ARCHITECTURE.md](docs/V1_ARCHITECTURE.md) for the full design.
