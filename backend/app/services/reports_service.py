from __future__ import annotations

from datetime import date
from typing import Optional
from sqlalchemy.orm import Session

from app.services.consumption_service import ConsumptionService
from app.services.material_set_service import MaterialSetService
from app.services.shortage_service import ShortageDetectionService
from app.services.stock_service import StockCalculationService


class ReportingService:
    """Aggregates inventory, consumption flags, and set availability for reports/dashboard."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.stock = StockCalculationService(db)
        self.consumption = ConsumptionService(db)
        self.shortage = ShortageDetectionService(db, self.stock)
        self.sets = MaterialSetService(db, self.stock)

    def build_summary(self, as_of_date: date, godown_name: Optional[str] = None) -> dict:
        balances = self.stock.get_all_godown_balances(
            as_of_date=as_of_date,
            godown_name=godown_name,
            include_closing_store=False,
        )
        flags = self.shortage.evaluate_godown_flags(as_of_date=as_of_date, godown_name=godown_name)
        set_evals = []
        if godown_name:
            set_evals = self.sets.evaluate_godown_sets(godown_name=godown_name, as_of_date=as_of_date)

        return {
            "as_of_date": as_of_date.isoformat(),
            "godown_filter": godown_name,
            "godown_balance_rows": len(balances),
            "negative_dip_count": sum(1 for b in balances if b.negative_dip_flagged),
            "zero_stock_count": sum(1 for f in flags if f.status == "ZERO_STOCK"),
            "low_stock_count": sum(1 for f in flags if f.status == "LOW_STOCK"),
            "excess_stock_count": sum(1 for f in flags if f.status == "EXCESS_STOCK"),
            "sets_evaluated": len(set_evals),
            "imbalanced_sets_count": sum(1 for s in set_evals if not s.is_balanced),
        }
