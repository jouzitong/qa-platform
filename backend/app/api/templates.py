from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.common import get_or_404
from app.database import get_session
from app.models import ApiDefinition, ApiTemplate, Project
from app.schemas import ApiTemplateCreate, ApiTemplateRead, ApiTemplateUpdate

router = APIRouter(prefix="/api-templates", tags=["api-templates"])


@router.get("", response_model=list[ApiTemplateRead])
def list_templates(
    project_id: str | None = Query(default=None), session: Session = Depends(get_session)
) -> list[ApiTemplate]:
    statement = (
        select(ApiTemplate)
        .options(selectinload(ApiTemplate.apis))
        .order_by(ApiTemplate.created_at.desc())
    )
    if project_id:
        statement = statement.where(ApiTemplate.project_id == project_id)
    return list(session.scalars(statement))


@router.post("", response_model=ApiTemplateRead, status_code=201)
def create_template(
    payload: ApiTemplateCreate, session: Session = Depends(get_session)
) -> ApiTemplate:
    get_or_404(session, Project, payload.project_id, "Project")
    template = ApiTemplate(**payload.model_dump())
    session.add(template)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Template name already exists in this project"
        ) from None
    session.refresh(template)
    return template


@router.get("/{template_id}", response_model=ApiTemplateRead)
def get_template(template_id: str, session: Session = Depends(get_session)) -> ApiTemplate:
    statement = (
        select(ApiTemplate)
        .where(ApiTemplate.id == template_id)
        .options(selectinload(ApiTemplate.apis))
    )
    template = session.scalar(statement)
    if not template:
        return get_or_404(session, ApiTemplate, template_id, "API template")
    return template


@router.patch("/{template_id}", response_model=ApiTemplateRead)
def update_template(
    template_id: str,
    payload: ApiTemplateUpdate,
    session: Session = Depends(get_session),
) -> ApiTemplate:
    template = get_or_404(session, ApiTemplate, template_id, "API template")
    values = payload.model_dump(exclude_none=True)
    if "protocol" in values and values["protocol"] != template.protocol:
        in_use = session.scalar(
            select(ApiDefinition.id)
            .where(ApiDefinition.template_id == template.id)
            .limit(1)
        )
        if in_use:
            raise HTTPException(
                status_code=409,
                detail="Cannot change protocol while the template is in use",
            )
    for field, value in values.items():
        setattr(template, field, value)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Template name already exists in this project"
        ) from None
    session.refresh(template)
    return template


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: str, session: Session = Depends(get_session)) -> Response:
    template = get_or_404(session, ApiTemplate, template_id, "API template")
    in_use = session.scalar(
        select(ApiDefinition.id).where(ApiDefinition.template_id == template.id).limit(1)
    )
    if in_use:
        raise HTTPException(status_code=409, detail="API template is in use")
    session.delete(template)
    session.commit()
    return Response(status_code=204)
