from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.definitions import router as definitions_router
from app.api.flows import router as flows_router
from app.api.projects import router as projects_router
from app.api.runs import router as runs_router
from app.api.templates import router as templates_router
from app.config import settings
from app.database import Base, engine, ensure_schema_compatibility


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    ensure_schema_compatibility()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Project-scoped HTTP/WebSocket API automation and test-flow execution.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(projects_router, prefix="/api/v1")
app.include_router(templates_router, prefix="/api/v1")
app.include_router(definitions_router, prefix="/api/v1")
app.include_router(flows_router, prefix="/api/v1")
app.include_router(runs_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
