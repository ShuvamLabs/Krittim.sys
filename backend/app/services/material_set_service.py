from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.database_models import MaterialSet
from app.services.stock_service import StockCalculationService


@dataclass(frozen=True)
class ComponentStatus:
    child_code: str
    child_name: str
    child_unit: str
    ratio_of_parent: float
    available_godown_qty: float
    required_for_available_parents: float
    max_parents_from_component: Optional[float]
    shortage_qty: float
    excess_qty: float


@dataclass(frozen=True)
class SetAvailability:
    set_no: str
    parent_code: str
    parent_name: str
    parent_unit: str
    godown_name: str
    as_of_date: date
    parent_available_qty: float
    complete_sets_possible: int
    limiting_child_code: Optional[str]
    is_balanced: bool
    components: List[ComponentStatus]


class MaterialSetService:
    """Evaluates parent-child material set availability using database definitions
    and godown balances from StockCalculationService.
    """

    def __init__(self, db: Session, stock_service: Optional[StockCalculationService] = None) -> None:
        self.db = db
        self.stock_service = stock_service or StockCalculationService(db)

    def evaluate_godown_sets(self, godown_name: str, as_of_date: date) -> List[SetAvailability]:
        sets = self.db.query(MaterialSet).order_by(MaterialSet.set_no).all()
        evaluations: List[SetAvailability] = []

        for mset in sets:
            parent_bal = self.stock_service.get_godown_balance(
                item_code=mset.parent_item.item_code,
                godown_name=godown_name,
                as_of_date=as_of_date,
            )
            parent_qty = parent_bal.effective_godown_stock

            comp_statuses: List[ComponentStatus] = []
            limiting_child: Optional[str] = None
            min_sets_cap: Optional[float] = float(int(parent_qty)) if parent_qty >= 0 else 0.0
            any_shortage = False

            for comp in sorted(mset.components, key=lambda c: c.child_item.item_code):
                child_bal = self.stock_service.get_godown_balance(
                    item_code=comp.child_item.item_code,
                    godown_name=godown_name,
                    as_of_date=as_of_date,
                )
                child_qty = child_bal.effective_godown_stock
                ratio = float(comp.ratio_of_parent)

                needed_for_parents = round(parent_qty * ratio, 6)
                shortage = round(max(0.0, needed_for_parents - child_qty), 6)
                excess = round(max(0.0, child_qty - needed_for_parents), 6)

                if shortage > 0.0:
                    any_shortage = True

                if ratio > 0:
                    cap = child_qty / ratio
                    if min_sets_cap is None or cap < min_sets_cap:
                        min_sets_cap = cap
                        limiting_child = comp.child_item.item_code
                    max_from_comp: Optional[float] = round(cap, 6)
                else:
                    max_from_comp = None

                comp_statuses.append(
                    ComponentStatus(
                        child_code=comp.child_item.item_code,
                        child_name=comp.child_name,
                        child_unit=comp.child_unit,
                        ratio_of_parent=ratio,
                        available_godown_qty=child_qty,
                        required_for_available_parents=needed_for_parents,
                        max_parents_from_component=max_from_comp,
                        shortage_qty=shortage,
                        excess_qty=excess,
                    )
                )

            complete_sets = int(max(0.0, min_sets_cap or 0.0))
            evaluations.append(
                SetAvailability(
                    set_no=mset.set_no,
                    parent_code=mset.parent_item.item_code,
                    parent_name=mset.parent_name,
                    parent_unit=mset.parent_unit,
                    godown_name=godown_name,
                    as_of_date=as_of_date,
                    parent_available_qty=parent_qty,
                    complete_sets_possible=complete_sets,
                    limiting_child_code=limiting_child,
                    is_balanced=not any_shortage,
                    components=comp_statuses,
                )
            )

        return evaluations
