# Development Notes

## Start Backend

```bash
cd backend
uvicorn app.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/api/health
```

## V1 Implementation Order

1. Add persistent repositories for students, questions, events, and progress.
2. Add LangGraph `MathTutorState` and graph nodes.
3. Wire `MockKTStateEngine` into the Core Learning Loop.
4. Add RAG chunk schema and local Chroma fallback.
5. Add TeachingTrace persistence and streaming.
6. Build the React learning dashboard.
