from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database_models import ContractorMovement, Godown, Item, Receipt, Transfer


@dataclass(frozen=True)
class GodownBalance:
    item_code: str
    item_name: str
    unit: str
    godown_name: str
    godown_code: Optional[str]
    as_of_date: date
    raw_godown_stock: float
    effective_godown_stock: float
    negative_dip_flagged: bool
    receipts_total: float
    transfers_in_total: float
    transfers_out_total: float
    issues_total: float
    returns_total: float


@dataclass(frozen=True)
class ContractorBalance:
    item_code: str
    item_name: str
    unit: str
    as_of_date: date
    issues_total: float
    returns_total: float
    consumption_total: float
    contractor_stock: float


class StockCalculationService:
    """Deterministic point-in-time inventory engine derived from movement history."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_godown_balance(
        self,
        item_code: str,
        godown_name: str,
        as_of_date: date,
    ) -> GodownBalance:
        item = self.db.query(Item).filter(Item.item_code == item_code).first()
        if item is None:
            raise ValueError(f"Unknown item_code: {item_code}")

        godown = self.db.query(Godown).filter(Godown.godown_name == godown_name).first()
        if godown is None:
            raise ValueError(f"Unknown godown_name: {godown_name}")

        receipts_total = float(
            self.db.query(func.coalesce(func.sum(Receipt.qty_received), 0.0))
            .filter(
                Receipt.item_id == item.id,
                Receipt.godown_id == godown.id,
                Receipt.date <= as_of_date,
                Receipt.qty_received > 0,
            )
            .scalar()
            or 0.0
        )

        transfers_in_total = float(
            self.db.query(func.coalesce(func.sum(Transfer.qty), 0.0))
            .filter(
                Transfer.item_id == item.id,
                Transfer.godown_id == godown.id,
                Transfer.direction == "IN",
                Transfer.date <= as_of_date,
                Transfer.qty > 0,
            )
            .scalar()
            or 0.0
        )

        transfers_out_total = float(
            self.db.query(func.coalesce(func.sum(Transfer.qty), 0.0))
            .filter(
                Transfer.item_id == item.id,
                Transfer.godown_id == godown.id,
                Transfer.direction == "OUT",
                Transfer.date <= as_of_date,
                Transfer.qty > 0,
            )
            .scalar()
            or 0.0
        )

        issues_total = float(
            self.db.query(func.coalesce(func.sum(ContractorMovement.qty), 0.0))
            .filter(
                ContractorMovement.item_id == item.id,
                ContractorMovement.godown_id == godown.id,
                ContractorMovement.type == "ISSUE",
                ContractorMovement.date <= as_of_date,
                ContractorMovement.qty > 0,
            )
            .scalar()
            or 0.0
        )

        returns_total = float(
            self.db.query(func.coalesce(func.sum(ContractorMovement.qty), 0.0))
            .filter(
                ContractorMovement.item_id == item.id,
                ContractorMovement.godown_id == godown.id,
                ContractorMovement.type == "RETURN",
                ContractorMovement.date <= as_of_date,
                ContractorMovement.qty > 0,
            )
            .scalar()
            or 0.0
        )

        raw_stock = (
            receipts_total
            + transfers_in_total
            - transfers_out_total
            - issues_total
            + returns_total
        )
        negative_flagged = raw_stock < 0.0
        effective_stock = max(0.0, raw_stock)

        return GodownBalance(
            item_code=item.item_code,
            item_name=item.item_name,
            unit=item.unit,
            godown_name=godown.godown_name,
            godown_code=godown.godown_code,
            as_of_date=as_of_date,
            raw_godown_stock=round(raw_stock, 6),
            effective_godown_stock=round(effective_stock, 6),
            negative_dip_flagged=negative_flagged,
            receipts_total=round(receipts_total, 6),
            transfers_in_total=round(transfers_in_total, 6),
            transfers_out_total=round(transfers_out_total, 6),
            issues_total=round(issues_total, 6),
            returns_total=round(returns_total, 6),
        )

    def get_contractor_balance(self, item_code: str, as_of_date: date) -> ContractorBalance:
        item = self.db.query(Item).filter(Item.item_code == item_code).first()
        if item is None:
            raise ValueError(f"Unknown item_code: {item_code}")

        rows: List[Tuple[str, float]] = (
            self.db.query(ContractorMovement.type, func.coalesce(func.sum(ContractorMovement.qty), 0.0))
            .filter(
                ContractorMovement.item_id == item.id,
                ContractorMovement.date <= as_of_date,
                ContractorMovement.qty > 0,
            )
            .group_by(ContractorMovement.type)
            .all()
        )
        totals: Dict[str, float] = {m_type: float(val) for m_type, val in rows}
        issues = totals.get("ISSUE", 0.0)
        returns = totals.get("RETURN", 0.0)
        consumption = totals.get("CONSUMPTION", 0.0)
        contractor_stock = issues - returns - consumption

        return ContractorBalance(
            item_code=item.item_code,
            item_name=item.item_name,
            unit=item.unit,
            as_of_date=as_of_date,
            issues_total=round(issues, 6),
            returns_total=round(returns, 6),
            consumption_total=round(consumption, 6),
            contractor_stock=round(contractor_stock, 6),
        )

    def get_all_godown_balances(
        self,
        as_of_date: date,
        item_code: Optional[str] = None,
        godown_name: Optional[str] = None,
        include_closing_store: bool = False,
    ) -> List[GodownBalance]:
        items_q = self.db.query(Item)
        if item_code:
            items_q = items_q.filter(Item.item_code == item_code)
        items = items_q.order_by(Item.item_code).all()

        godowns_q = self.db.query(Godown)
        if godown_name:
            godowns_q = godowns_q.filter(Godown.godown_name == godown_name)
        elif not include_closing_store:
            godowns_q = godowns_q.filter(Godown.is_closing_store.is_(False))
        godowns = godowns_q.order_by(Godown.godown_name).all()

        results: List[GodownBalance] = []
        for itm in items:
            for gdw in godowns:
                results.append(self.get_godown_balance(itm.item_code, gdw.godown_name, as_of_date))
        return results
