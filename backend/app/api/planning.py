from __future__ import annotations

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.services.planning_service import PlanningService
from app.services.simulation_service import SimulationService

router = APIRouter(prefix="/planning", tags=["Planning & Simulation"])


class SimulationRequestIn(BaseModel):
    name: str = "Lumino Historical Replay"
    start_date: date = date(2023, 3, 1)
    end_date: date = date(2026, 10, 31)
    godown: Optional[str] = None
    item_code: Optional[str] = None


@router.get("/recommendations", response_model=list[dict])
def get_recommendations(
    decision_date: date = Query(...),
    godown: Optional[str] = Query(None),
    item_code: Optional[str] = Query(None),
    horizon_months: int = Query(1, ge=1, le=12),
    db: Session = Depends(get_db),
):
    svc = PlanningService(db)
    return svc.generate_recommendations(
        decision_date=decision_date,
        godown_name=godown,
        item_code=item_code,
        horizon_months=horizon_months,
    )


@router.post("/simulate", response_model=dict)
def run_historical_simulation(req: SimulationRequestIn, db: Session = Depends(get_db)):
    svc = SimulationService(db)
    return svc.run_simulation(
        name=req.name,
        start_date=req.start_date,
        end_date=req.end_date,
        godown_name=req.godown,
        item_code=req.item_code,
    )
