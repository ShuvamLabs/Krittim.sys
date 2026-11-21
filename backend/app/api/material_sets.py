from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.database_models import MaterialSet
from app.schemas.response_schemas import ComponentStatusOut, SetAvailabilityOut
from app.services.material_set_service import MaterialSetService

router = APIRouter(prefix="/material-sets", tags=["Material Sets"])


@router.get("", response_model=list[dict])
def list_material_sets(db: Session = Depends(get_db)):
    sets = db.query(MaterialSet).order_by(MaterialSet.set_no).all()
    return [
        {
            "set_no": s.set_no,
            "parent_code": s.parent_item.item_code,
            "parent_name": s.parent_name,
            "parent_unit": s.parent_unit,
            "components": [
                {
                    "child_code": c.child_item.item_code,
                    "child_name": c.child_name,
                    "child_unit": c.child_unit,
                    "ratio_of_parent": c.ratio_of_parent,
                }
                for c in s.components
            ],
        }
        for s in sets
    ]


@router.get("/availability", response_model=list[SetAvailabilityOut])
def get_set_availability(
    godown: str = Query(...),
    as_of_date: date = Query(...),
    db: Session = Depends(get_db),
):
    svc = MaterialSetService(db)
    evals = svc.evaluate_godown_sets(godown_name=godown, as_of_date=as_of_date)
    return [
        SetAvailabilityOut(
            set_no=ev.set_no,
            parent_code=ev.parent_code,
            parent_name=ev.parent_name,
            parent_unit=ev.parent_unit,
            godown_name=ev.godown_name,
            as_of_date=ev.as_of_date,
            parent_available_qty=ev.parent_available_qty,
            complete_sets_possible=ev.complete_sets_possible,
            limiting_child_code=ev.limiting_child_code,
            is_balanced=ev.is_balanced,
            components=[ComponentStatusOut(**c.__dict__) for c in ev.components],
        )
        for ev in evals
    ]
