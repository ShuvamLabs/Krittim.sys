from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.services.stock_service import StockCalculationService


@dataclass(frozen=True)
class StockFlagItem:
    item_code: str
    item_name: str
    unit: str
    godown_name: str
    godown_code: Optional[str]
    as_of_date: date
    effective_godown_stock: float
    raw_godown_stock: float
    negative_dip_flagged: bool
    status: str  # "ZERO_STOCK" | "NEGATIVE_DIP" | "LOW_STOCK" | "EXCESS_STOCK" | "NORMAL"
    threshold_used: Optional[float]


class ShortageDetectionService:
    """Identifies zero/negative/low godown balances and high/excess godown
    stock relative to a configurable threshold (defaults to item lead_time_days
    or explicit stock threshold).
    """

    def __init__(self, db: Session, stock_service: Optional[StockCalculationService] = None) -> None:
        self.db = db
        self.stock_service = stock_service or StockCalculationService(db)

    def evaluate_godown_flags(
        self,
        as_of_date: date,
        godown_name: Optional[str] = None,
        item_code: Optional[str] = None,
        low_threshold: float = 10.0,
        excess_threshold: float = 10000.0,
    ) -> List[StockFlagItem]:
        balances = self.stock_service.get_all_godown_balances(
            as_of_date=as_of_date,
            item_code=item_code,
            godown_name=godown_name,
            include_closing_store=False,
        )
        flagged: List[StockFlagItem] = []

        for bal in balances:
            if bal.negative_dip_flagged:
                status = "NEGATIVE_DIP"
                thresh = 0.0
            elif bal.effective_godown_stock == 0.0:
                status = "ZERO_STOCK"
                thresh = 0.0
            elif bal.effective_godown_stock <= low_threshold:
                status = "LOW_STOCK"
                thresh = low_threshold
            elif bal.effective_godown_stock >= excess_threshold:
                status = "EXCESS_STOCK"
                thresh = excess_threshold
            else:
                status = "NORMAL"
                thresh = None

            flagged.append(
                StockFlagItem(
                    item_code=bal.item_code,
                    item_name=bal.item_name,
                    unit=bal.unit,
                    godown_name=bal.godown_name,
                    godown_code=bal.godown_code,
                    as_of_date=as_of_date,
                    effective_godown_stock=bal.effective_godown_stock,
                    raw_godown_stock=bal.raw_godown_stock,
                    negative_dip_flagged=bal.negative_dip_flagged,
                    status=status,
                    threshold_used=thresh,
                )
            )
        return flagged
