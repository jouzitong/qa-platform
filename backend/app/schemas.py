from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.success_contract import default_success_contract


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
    key: str = Field(min_length=1, max_length=120)
    template_id: str | None = None
    assertion_profile_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    protocol: Literal["http", "ws"] = "http"
    description: str = ""
    request: dict[str, Any] = Field(default_factory=dict)
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    success_contract: dict[str, Any] = Field(default_factory=default_success_contract)
    response_variants: list[dict[str, Any]] = Field(default_factory=list)


class ApiUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=120)
    template_id: str | None = None
    assertion_profile_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    protocol: Literal["http", "ws"] | None = None
    description: str | None = None
    request: dict[str, Any] | None = None
    parameters: list[dict[str, Any]] | None = None
    examples: list[dict[str, Any]] | None = None
    success_contract: dict[str, Any] | None = None
    response_variants: list[dict[str, Any]] | None = None


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


class AssertionDefinitionCreate(BaseModel):
    project_id: str
    key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    engine: Literal["path", "json_schema", "expression"] = "path"
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    default_params: dict[str, Any] = Field(default_factory=dict)
    severity: Literal["success", "error", "warning"] = "success"
    message: str = ""


class AssertionDefinitionUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    engine: Literal["path", "json_schema", "expression"] | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    default_params: dict[str, Any] | None = None
    severity: Literal["success", "error", "warning"] | None = None
    message: str | None = None


class AssertionDefinitionRead(AssertionDefinitionCreate, ORMModel):
    id: str
    created_at: datetime
    updated_at: datetime


class AssertionProfileCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    protocol: Literal["http", "ws"] = "http"
    description: str = ""
    is_default: bool = False
    bindings: list[dict[str, Any]] = Field(default_factory=list)


class AssertionProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    protocol: Literal["http", "ws"] | None = None
    description: str | None = None
    is_default: bool | None = None
    bindings: list[dict[str, Any]] | None = None


class AssertionProfileRead(AssertionProfileCreate, ORMModel):
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
    disabled_assertion_ids: list[str] = Field(default_factory=list)
    extractors: list[dict[str, Any]] = Field(default_factory=list)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)


class FlowCreate(BaseModel):
    project_id: str
    key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)
    steps: list[FlowStep] = Field(default_factory=list)


class FlowUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    variables: dict[str, Any] | None = None
    steps: list[FlowStep] | None = None


class FlowRead(FlowCreate, ORMModel):
    id: str
    created_at: datetime
    updated_at: datetime


class TestPlanItem(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    type: Literal["api", "flow"]
    target_id: str
    enabled: bool = True


class TestPlanCreate(BaseModel):
    project_id: str
    key: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    items: list[TestPlanItem] = Field(default_factory=list)


class TestPlanUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=120)
    version: str | None = Field(default=None, min_length=1, max_length=60)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    items: list[TestPlanItem] | None = None


class TestPlanRead(TestPlanCreate, ORMModel):
    id: str
    created_at: datetime
    updated_at: datetime


class TestPlanRunRead(ORMModel):
    id: str
    plan_id: str
    status: str
    inputs: dict[str, Any]
    results: list[dict[str, Any]]
    total_count: int
    passed_count: int
    failed_count: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


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
    assertion_results: list[dict[str, Any]]
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
