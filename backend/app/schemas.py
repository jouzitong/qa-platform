from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    variables: dict[str, Any] | None = None


class ProjectRead(ProjectCreate, ORMModel):
    id: str
    created_at: datetime
    updated_at: datetime


class ApiCreate(BaseModel):
    project_id: str
    template_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    protocol: Literal["http", "ws"] = "http"
    description: str = ""
    request: dict[str, Any] = Field(default_factory=dict)
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)


class ApiUpdate(BaseModel):
    template_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    protocol: Literal["http", "ws"] | None = None
    description: str | None = None
    request: dict[str, Any] | None = None
    parameters: list[dict[str, Any]] | None = None
    examples: list[dict[str, Any]] | None = None


class ApiRead(ApiCreate, ORMModel):
    id: str
    created_at: datetime
    updated_at: datetime


class ApiTemplateCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    protocol: Literal["http", "ws"] = "http"
    description: str = ""
    request: dict[str, Any] = Field(default_factory=dict)
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)


class ApiTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    protocol: Literal["http", "ws"] | None = None
    description: str | None = None
    request: dict[str, Any] | None = None
    parameters: list[dict[str, Any]] | None = None
    examples: list[dict[str, Any]] | None = None


class ApiTemplateRead(ApiTemplateCreate, ORMModel):
    id: str
    usage_count: int
    created_at: datetime
    updated_at: datetime


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=1, ge=1, le=10)
    interval_ms: int = Field(default=0, ge=0, le=300_000)
    backoff_multiplier: float = Field(default=1, ge=1, le=10)


class FlowStep(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    api_id: str
    enabled: bool = True
    request: dict[str, Any] = Field(default_factory=dict)
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    extractors: list[dict[str, Any]] = Field(default_factory=list)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)


class FlowCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)
    steps: list[FlowStep] = Field(default_factory=list)


class FlowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    variables: dict[str, Any] | None = None
    steps: list[FlowStep] | None = None


class FlowRead(FlowCreate, ORMModel):
    id: str
    created_at: datetime
    updated_at: datetime


class ExecuteRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    request: dict[str, Any] = Field(default_factory=dict)


class StepRunRead(ORMModel):
    id: str
    step_id: str
    step_name: str
    position: int
    attempt: int
    status: str
    duration_ms: float
    request_snapshot: dict[str, Any]
    response_snapshot: dict[str, Any] | None
    extracted: dict[str, Any]
    error: str | None
    created_at: datetime


class RunRead(ORMModel):
    id: str
    flow_id: str
    status: str
    inputs: dict[str, Any]
    context: dict[str, Any]
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    step_runs: list[StepRunRead] = Field(default_factory=list)
