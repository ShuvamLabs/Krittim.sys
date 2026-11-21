from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.services.shortage_service import ShortageDetectionService
from app.services.stock_service import ContractorBalance, GodownBalance, StockCalculationService


class InventoryService:
    """Provides high-level item-wise and godown-wise inventory summaries
    combining balances and status flags.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.stock = StockCalculationService(db)
        self.shortage = ShortageDetectionService(db, self.stock)

    def get_summary(
        self,
        as_of_date: date,
        godown_name: Optional[str] = None,
        item_code: Optional[str] = None,
    ) -> Dict:
        balances: List[GodownBalance] = self.stock.get_all_godown_balances(
            as_of_date=as_of_date,
            item_code=item_code,
            godown_name=godown_name,
        )
        return {
            "as_of_date": as_of_date,
            "godown_count": len({b.godown_name for b in balances}),
            "item_count": len({b.item_code for b in balances}),
            "negative_dip_count": sum(1 for b in balances if b.negative_dip_flagged),
            "zero_stock_count": sum(1 for b in balances if b.effective_godown_stock == 0.0),
            "balances": balances,
        }

    def get_item_overview(self, item_code: str, as_of_date: date) -> Dict:
        g_balances: List[GodownBalance] = self.stock.get_all_godown_balances(
            as_of_date=as_of_date,
            item_code=item_code,
        )
        c_balance: ContractorBalance = self.stock.get_contractor_balance(
            item_code=item_code,
            as_of_date=as_of_date,
        )
        return {
            "item_code": item_code,
            "as_of_date": as_of_date,
            "contractor_balance": c_balance,
            "godown_balances": g_balances,
        }
