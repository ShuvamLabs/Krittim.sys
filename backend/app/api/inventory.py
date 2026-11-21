from __future__ import annotations

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.schemas.response_schemas import ContractorBalanceOut, GodownBalanceOut, InventorySummaryOut
from app.services.stock_service import StockCalculationService

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.get("/summary", response_model=InventorySummaryOut)
def get_inventory_summary(
    as_of_date: date = Query(..., description="Point-in-time date YYYY-MM-DD"),
    godown: Optional[str] = Query(None),
    item_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    svc = StockCalculationService(db)
    try:
        balances = svc.get_all_godown_balances(
            as_of_date=as_of_date,
            item_code=item_code,
            godown_name=godown,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return InventorySummaryOut(
        as_of_date=as_of_date,
        godown_count=len({b.godown_name for b in balances}),
        item_count=len({b.item_code for b in balances}),
        negative_dip_count=sum(1 for b in balances if b.negative_dip_flagged),
        zero_stock_count=sum(1 for b in balances if b.effective_godown_stock == 0.0),
        balances=[GodownBalanceOut(**b.__dict__) for b in balances],
    )


@router.get("/items", response_model=list[GodownBalanceOut])
def list_item_balances(
    as_of_date: date = Query(...),
    godown: Optional[str] = Query(None),
    item_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    svc = StockCalculationService(db)
    try:
        balances = svc.get_all_godown_balances(
            as_of_date=as_of_date,
            item_code=item_code,
            godown_name=godown,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [GodownBalanceOut(**b.__dict__) for b in balances]


@router.get("/godowns", response_model=list[GodownBalanceOut])
def list_godown_balances(
    as_of_date: date = Query(...),
    godown: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    svc = StockCalculationService(db)
    try:
        balances = svc.get_all_godown_balances(
            as_of_date=as_of_date,
            godown_name=godown,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [GodownBalanceOut(**b.__dict__) for b in balances]


@router.get("/items/{item_code}", response_model=dict)
def get_item_detail(
    item_code: str,
    as_of_date: date = Query(...),
    db: Session = Depends(get_db),
):
    svc = StockCalculationService(db)
    try:
        g_balances = svc.get_all_godown_balances(as_of_date=as_of_date, item_code=item_code)
        c_bal = svc.get_contractor_balance(item_code=item_code, as_of_date=as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "item_code": item_code,
        "as_of_date": as_of_date.isoformat(),
        "contractor_balance": ContractorBalanceOut(**c_bal.__dict__).model_dump(),
        "godown_balances": [GodownBalanceOut(**b.__dict__).model_dump() for b in g_balances],
    }
