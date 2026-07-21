from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")


def get_or_404(session: Session, model: type[ModelT], item_id: str, label: str) -> ModelT:
    item = session.get(model, item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return item
