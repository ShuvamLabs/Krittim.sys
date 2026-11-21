from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.schemas.response_schemas import MonthlyConsumptionPointOut
from app.services.consumption_service import ConsumptionService

router = APIRouter(prefix="/consumption", tags=["Consumption"])


@router.get("/trends", response_model=list[MonthlyConsumptionPointOut])
def get_consumption_trends(
    item_code: Optional[str] = Query(None),
    month_from: Optional[str] = Query(None, description="YYYY-MM"),
    month_to: Optional[str] = Query(None, description="YYYY-MM"),
    db: Session = Depends(get_db),
):
    svc = ConsumptionService(db)
    points = svc.get_monthly_trends(item_code=item_code, month_from=month_from, month_to=month_to)
    return [MonthlyConsumptionPointOut(**p.__dict__) for p in points]
