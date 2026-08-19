from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_or_404, normalize_group_path
from app.database import get_session
from app.models import ApiDefinition, ApiGroup, Project
from app.schemas import ApiGroupCreate, ApiGroupRead, ApiGroupUpdate

router = APIRouter(prefix="/api-groups", tags=["api-groups"])


def normalize_group_name(value: object | None) -> str:
    name = str(value or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="目录名称不能为空")
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=422, detail="目录名称不能包含斜杠")
    if name in {".", ".."}:
        raise HTTPException(status_code=422, detail="目录名称不合法")
    return name


def parent_group_path(path: str) -> str:
    normalized = normalize_group_path(path)
    if normalized == "/":
        return "/"
    return normalized.rsplit("/", 1)[0] or "/"


def child_group_path(parent_path: str, name: str) -> str:
    parent = normalize_group_path(parent_path)
    normalized_name = normalize_group_name(name)
    path = f"/{normalized_name}" if parent == "/" else f"{parent}/{normalized_name}"
    if len(path) > 240:
        raise HTTPException(status_code=422, detail="目录路径不能超过 240 个字符")
    return path


def ensure_api_group_path(session: Session, project_id: str, group_path: object | None) -> str:
    """Create the persisted directory chain for an API path when needed."""
    normalized = normalize_group_path(group_path)
    if normalized == "/":
        return normalized

    segments = normalized.strip("/").split("/")
    current_path = ""
    created = False
    for segment in segments:
        current_path = f"{current_path}/{segment}"
        group = session.scalar(
            select(ApiGroup).where(
                ApiGroup.project_id == project_id,
                ApiGroup.path == current_path,
            )
        )
        if group:
            continue
        session.add(
            ApiGroup(
                project_id=project_id,
                path=current_path,
                name=segment,
            )
        )
        created = True
    if created:
        session.flush()
    return normalized


@router.get("", response_model=list[ApiGroupRead])
def list_api_groups(
    project_id: str | None = Query(default=None), session: Session = Depends(get_session)
) -> list[ApiGroup]:
    statement = select(ApiGroup).order_by(ApiGroup.path.asc())
    if project_id:
        statement = statement.where(ApiGroup.project_id == project_id)
    return list(session.scalars(statement))


@router.post("", response_model=ApiGroupRead, status_code=201)
def create_api_group(
    payload: ApiGroupCreate, session: Session = Depends(get_session)
) -> ApiGroup:
    get_or_404(session, Project, payload.project_id, "Project")
    parent_path = normalize_group_path(payload.parent_path)
    if parent_path != "/":
        ensure_api_group_path(session, payload.project_id, parent_path)
    path = child_group_path(parent_path, payload.name)
    existing = session.scalar(
        select(ApiGroup).where(
            ApiGroup.project_id == payload.project_id,
            ApiGroup.path == path,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="目录已存在")
    group = ApiGroup(
        project_id=payload.project_id,
        path=path,
        name=normalize_group_name(payload.name),
    )
    session.add(group)
    commit_or_conflict(session, "目录已存在")
    session.refresh(group)
    return group


@router.patch("/{group_id}", response_model=ApiGroupRead)
def update_api_group(
    group_id: str, payload: ApiGroupUpdate, session: Session = Depends(get_session)
) -> ApiGroup:
    group = get_or_404(session, ApiGroup, group_id, "API 目录")
    new_name = normalize_group_name(payload.name)
    old_path = normalize_group_path(group.path)
    new_path = child_group_path(parent_group_path(old_path), new_name)
    if new_path == old_path:
        return group

    conflict = session.scalar(
        select(ApiGroup).where(
            ApiGroup.project_id == group.project_id,
            ApiGroup.path == new_path,
            ApiGroup.id != group.id,
        )
    )
    if conflict:
        raise HTTPException(status_code=409, detail="目标目录已存在")

    descendants = list(
        session.scalars(
            select(ApiGroup).where(
                ApiGroup.project_id == group.project_id,
                ApiGroup.path.like(f"{old_path}/%"),
            )
        )
    )
    definitions = list(
        session.scalars(
            select(ApiDefinition).where(
                ApiDefinition.project_id == group.project_id,
                or_(
                    ApiDefinition.group_path == old_path,
                    ApiDefinition.group_path.like(f"{old_path}/%"),
                ),
            )
        )
    )
    group.path = new_path
    group.name = new_name
    for descendant in descendants:
        descendant.path = f"{new_path}{descendant.path[len(old_path):]}"
        descendant.name = descendant.path.rsplit("/", 1)[-1]
    for definition in definitions:
        definition.group_path = f"{new_path}{definition.group_path[len(old_path):]}"

    commit_or_conflict(session, "目标目录已存在")
    session.refresh(group)
    return group


@router.delete("/{group_id}", status_code=204)
def delete_api_group(group_id: str, session: Session = Depends(get_session)) -> Response:
    group = get_or_404(session, ApiGroup, group_id, "API 目录")
    path = normalize_group_path(group.path)
    child = session.scalar(
        select(ApiGroup.id).where(
            ApiGroup.project_id == group.project_id,
            ApiGroup.path.like(f"{path}/%"),
        ).limit(1)
    )
    if child:
        raise HTTPException(status_code=409, detail="目录下还有子目录，不能删除")
    definition = session.scalar(
        select(ApiDefinition.id).where(
            ApiDefinition.project_id == group.project_id,
            or_(
                ApiDefinition.group_path == path,
                ApiDefinition.group_path.like(f"{path}/%"),
            ),
        ).limit(1)
    )
    if definition:
        raise HTTPException(status_code=409, detail="目录下还有 API，不能删除")
    session.delete(group)
    session.commit()
    return Response(status_code=204)
