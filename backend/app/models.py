from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    variables: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    apis: Mapped[list["ApiDefinition"]] = relationship(cascade="all, delete-orphan")
    api_templates: Mapped[list["ApiTemplate"]] = relationship(cascade="all, delete-orphan")
    assertion_definitions: Mapped[list["AssertionDefinition"]] = relationship(
        cascade="all, delete-orphan"
    )
    assertion_profiles: Mapped[list["AssertionProfile"]] = relationship(
        cascade="all, delete-orphan"
    )
    flows: Mapped[list["TestFlow"]] = relationship(cascade="all, delete-orphan")


class ApiTemplate(TimestampMixin, Base):
    __tablename__ = "api_templates"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_template_project_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    protocol: Mapped[str] = mapped_column(String(10), default="http")
    description: Mapped[str] = mapped_column(Text, default="")
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parameters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    examples: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    apis: Mapped[list["ApiDefinition"]] = relationship(back_populates="template")

    @property
    def usage_count(self) -> int:
        return len(self.apis)


class ApiDefinition(TimestampMixin, Base):
    __tablename__ = "api_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_templates.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    assertion_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("assertion_profiles.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    protocol: Mapped[str] = mapped_column(String(10), default="http")
    description: Mapped[str] = mapped_column(Text, default="")
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parameters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    examples: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    response_variants: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    template: Mapped[ApiTemplate | None] = relationship(back_populates="apis")
    assertion_profile: Mapped["AssertionProfile | None"] = relationship(
        back_populates="apis"
    )


class AssertionDefinition(TimestampMixin, Base):
    __tablename__ = "assertion_definitions"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_assertion_definition_project_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    engine: Mapped[str] = mapped_column(String(20), default="path")
    description: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    default_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(10), default="error")
    message: Mapped[str] = mapped_column(Text, default="")


class AssertionProfile(TimestampMixin, Base):
    __tablename__ = "assertion_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_assertion_profile_project_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    protocol: Mapped[str] = mapped_column(String(10), default="http")
    description: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(default=False, index=True)
    bindings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    apis: Mapped[list[ApiDefinition]] = relationship(back_populates="assertion_profile")

    @property
    def usage_count(self) -> int:
        return len(self.apis)


class TestFlow(TimestampMixin, Base):
    __tablename__ = "test_flows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    variables: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    runs: Mapped[list["TestRun"]] = relationship(cascade="all, delete-orphan")


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    flow_id: Mapped[str] = mapped_column(
        ForeignKey("test_flows.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    step_runs: Mapped[list["StepRun"]] = relationship(
        cascade="all, delete-orphan", order_by="StepRun.position, StepRun.attempt"
    )


class StepRun(Base):
    __tablename__ = "step_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[str] = mapped_column(String(80))
    step_name: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20))
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    extracted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    assertion_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
