from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import get_or_404
from app.database import get_session
from app.imports.archive import ImportArchiveError, parse_import_archive
from app.imports.service import apply_import, build_preview, mark_reviewed
from app.models import ImportSession
from app.schemas import ImportSessionRead

router = APIRouter(prefix="/imports", tags=["imports"])


def _filename(value: str) -> str:
    decoded = unquote(value or "import.zip").strip()
    return decoded[-255:] or "import.zip"


async def _create_preview(
    request: Request,
    session: Session,
    project_id: str | None,
    filename: str,
    source: str,
) -> ImportSession:
    content = await request.body()
    if not content:
        raise HTTPException(status_code=422, detail="请上传导入压缩包")
    try:
        package = parse_import_archive(filename, content)
        package, preview, errors, warnings, resolved_project_id = build_preview(
            session, package, project_id
        )
    except ImportArchiveError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    import_session = ImportSession(
        project_id=resolved_project_id,
        status="pending",
        filename=filename,
        archive_format="zip",
        package_version=str(package.get("package_version") or "1.0"),
        source={"channel": source or "workspace", **(package.get("source") or {})},
        package=package,
        preview=preview,
        errors=errors,
        warnings=warnings,
    )
    session.add(import_session)
    session.commit()
    session.refresh(import_session)
    return import_session


@router.get("", response_model=list[ImportSessionRead])
def list_imports(
    project_id: str | None = Query(default=None), session: Session = Depends(get_session)
) -> list[ImportSession]:
    statement = select(ImportSession).order_by(ImportSession.created_at.desc())
    if project_id:
        statement = statement.where(ImportSession.project_id == project_id)
    return list(session.scalars(statement))


@router.post("/preview", response_model=ImportSessionRead, status_code=201)
async def preview_import(
    request: Request,
    project_id: str | None = Query(default=None),
    import_filename: str = Header(default="import.zip", alias="X-Import-Filename"),
    import_source: str = Header(default="workspace", alias="X-Import-Source"),
    session: Session = Depends(get_session),
) -> ImportSession:
    return await _create_preview(
        request, session, project_id, _filename(import_filename), import_source
    )


@router.post("/one-click", response_model=ImportSessionRead, status_code=201)
async def one_click_import(
    request: Request,
    project_id: str | None = Query(default=None),
    import_filename: str = Header(default="import.zip", alias="X-Import-Filename"),
    import_source: str = Header(default="external", alias="X-Import-Source"),
    session: Session = Depends(get_session),
) -> ImportSession:
    """External entry point: create a pending approval session, never apply immediately."""
    return await _create_preview(
        request, session, project_id, _filename(import_filename), import_source
    )


@router.get("/{import_id}", response_model=ImportSessionRead)
def get_import(import_id: str, session: Session = Depends(get_session)) -> ImportSession:
    return get_or_404(session, ImportSession, import_id, "Import session")


@router.post("/{import_id}/approve", response_model=ImportSessionRead)
def approve_import(import_id: str, session: Session = Depends(get_session)) -> ImportSession:
    import_session = get_or_404(session, ImportSession, import_id, "Import session")
    if import_session.status != "pending":
        raise HTTPException(status_code=409, detail="只有待审批的导入会话可以确认")
    if import_session.errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "导入包存在校验错误", "errors": import_session.errors},
        )
    try:
        mark_reviewed(import_session, "approved")
        apply_import(session, import_session)
        import_session.status = "applied"
        import_session.applied_at = import_session.reviewed_at
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        failed = session.get(ImportSession, import_id)
        if failed:
            failed.status = "failed"
            failed.errors = [f"导入应用失败：{exc.orig}"]
            session.commit()
        raise HTTPException(status_code=409, detail="导入应用失败，业务数据已回滚") from None
    except Exception as exc:
        session.rollback()
        failed = session.get(ImportSession, import_id)
        if failed:
            failed.status = "failed"
            failed.errors = [f"导入应用失败：{exc}"]
            session.commit()
        raise HTTPException(status_code=422, detail="导入应用失败，业务数据已回滚") from None
    session.refresh(import_session)
    return import_session


@router.post("/{import_id}/reject", response_model=ImportSessionRead)
def reject_import(import_id: str, session: Session = Depends(get_session)) -> ImportSession:
    import_session = get_or_404(session, ImportSession, import_id, "Import session")
    if import_session.status != "pending":
        raise HTTPException(status_code=409, detail="只有待审批的导入会话可以拒绝")
    mark_reviewed(import_session, "rejected")
    session.commit()
    session.refresh(import_session)
    return import_session
