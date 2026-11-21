from __future__ import annotations

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.schemas.response_schemas import MovementHistoryOut, MovementRecordOut
from app.services.movement_service import MovementService

router = APIRouter(prefix="/movements", tags=["Movements"])


@router.get("/history", response_model=MovementHistoryOut)
def get_movement_history(
    item_code: Optional[str] = Query(None),
    godown: Optional[str] = Query(None),
    movement_type: Optional[str] = Query(None, description="RECEIPT | TRANSFER | ISSUE | RETURN | CONSUMPTION"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    svc = MovementService(db)
    total, rows = svc.get_movements(
        item_code=item_code,
        godown_name=godown,
        movement_type=movement_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return MovementHistoryOut(
        total=total,
        limit=limit,
        offset=offset,
        items=[MovementRecordOut(**r.__dict__) for r in rows],
    )
