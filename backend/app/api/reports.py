from __future__ import annotations

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.services.reports_service import ReportingService

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/summary", response_model=dict)
def get_report_summary(
    as_of_date: date = Query(...),
    godown: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    svc = ReportingService(db)
    return svc.build_summary(as_of_date=as_of_date, godown_name=godown)
