from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.database_models import ContractorMovement, Item


@dataclass(frozen=True)
class MonthlyConsumptionPoint:
    month: str
    item_code: str
    item_name: str
    unit: str
    consumed_qty: float
    cumulative_consumed_qty: float


class ConsumptionService:
    """Computes actual project-level material consumption trends from
    CONSUMPTION rows in contractor_movements.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_monthly_trends(
        self,
        item_code: Optional[str] = None,
        month_from: Optional[str] = None,
        month_to: Optional[str] = None,
    ) -> List[MonthlyConsumptionPoint]:
        q = (
            self.db.query(ContractorMovement, Item)
            .join(Item, ContractorMovement.item_id == Item.id)
            .filter(
                ContractorMovement.type == "CONSUMPTION",
                ContractorMovement.qty > 0,
            )
        )
        if item_code:
            q = q.filter(Item.item_code == item_code)

        buckets: dict[tuple[str, str], dict] = {}
        for cm, itm in q.all():
            ym = cm.date.strftime("%Y-%m")
            if month_from and ym < month_from:
                continue
            if month_to and ym > month_to:
                continue
            key = (itm.item_code, ym)
            if key not in buckets:
                buckets[key] = {
                    "month": ym,
                    "item_code": itm.item_code,
                    "item_name": itm.item_name,
                    "unit": itm.unit,
                    "consumed_qty": 0.0,
                }
            buckets[key]["consumed_qty"] += float(cm.qty)

        sorted_keys = sorted(buckets.keys(), key=lambda k: (k[0], k[1]))
        cum_by_item: dict[str, float] = {}
        points: List[MonthlyConsumptionPoint] = []

        for key in sorted_keys:
            row = buckets[key]
            icode = row["item_code"]
            qty = round(row["consumed_qty"], 6)
            cum = round(cum_by_item.get(icode, 0.0) + qty, 6)
            cum_by_item[icode] = cum
            points.append(
                MonthlyConsumptionPoint(
                    month=row["month"],
                    item_code=icode,
                    item_name=row["item_name"],
                    unit=row["unit"],
                    consumed_qty=qty,
                    cumulative_consumed_qty=cum,
                )
            )

        points.sort(key=lambda p: (p.month, p.item_code))
        return points
