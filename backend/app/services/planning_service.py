from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Optional
from sqlalchemy.orm import Session

from app.integrations.recommendation_engine import (
    PlanningInput,
    PlanningRecommendation,
    RecommendationEngineAdapter,
)
from app.models.database_models import ContractorMovement, Godown, Item
from app.services.stock_service import StockCalculationService

DEFAULT_PLANNER_SRC = Path(r"C:\Users\VICTUS\OneDrive\Desktop\Krittim.sys\src")


class PlanningService:
    """Builds point-in-time planning inputs strictly up to decision_date
    (preventing future-data leakage) and validates recommendations.
    """

    def __init__(
        self,
        db: Session,
        engine: Optional[RecommendationEngineAdapter] = None,
        stock_service: Optional[StockCalculationService] = None,
        planner_src_dir: Optional[Path] = DEFAULT_PLANNER_SRC,
    ) -> None:
        self.db = db
        self.engine = engine or RecommendationEngineAdapter(
            planner_dir=planner_src_dir,
            lookback_months=3,
            safety_buffer=0.15,
            hold_multiplier=1.50,
        )
        if self.engine._custom_fn is None and self.engine._planner_cache is None:
            self.engine.load_shuvam_planner_df(planner_src_dir)
        self.stock_service = stock_service or StockCalculationService(db)

    def _consumption_up_to(self, item_id: int, as_of_date: date) -> float:
        rows = (
            self.db.query(ContractorMovement.qty)
            .filter(
                ContractorMovement.item_id == item_id,
                ContractorMovement.type == "CONSUMPTION",
                ContractorMovement.date <= as_of_date,
                ContractorMovement.qty > 0,
            )
            .all()
        )
        return float(sum(float(r[0]) for r in rows))

    def generate_recommendations(
        self,
        decision_date: date,
        godown_name: Optional[str] = None,
        item_code: Optional[str] = None,
        horizon_months: int = 1,
        simulated_stock_override: Optional[float] = None,
        simulated_incoming_stock: float = 0.0,
    ) -> List[dict]:
        items_q = self.db.query(Item)
        if item_code:
            items_q = items_q.filter(Item.item_code == item_code)
        items = items_q.order_by(Item.item_code).all()

        godowns_q = self.db.query(Godown).filter(Godown.is_closing_store.is_(False))
        if godown_name:
            godowns_q = godowns_q.filter(Godown.godown_name == godown_name)
        godowns = godowns_q.order_by(Godown.godown_name).all()

        results: List[dict] = []
        for itm in items:
            cum_cons = self._consumption_up_to(itm.id, decision_date)
            elapsed_days = max(30, (decision_date - date(2023, 3, 1)).days)
            avg_monthly_cons = cum_cons / (elapsed_days / 30.0)

            for gdw in godowns:
                bal = self.stock_service.get_godown_balance(itm.item_code, gdw.godown_name, decision_date)
                avail_stock = simulated_stock_override if simulated_stock_override is not None else bal.effective_godown_stock
                p_in = PlanningInput(
                    item_code=itm.item_code,
                    godown_name=gdw.godown_name,
                    decision_date=decision_date,
                    lead_time_days=int(itm.lead_time_days or 30),
                    current_godown_stock=avail_stock,
                    incoming_stock=simulated_incoming_stock,
                    historical_consumption_to_date=round(cum_cons, 4),
                    recent_monthly_consumption=round(avg_monthly_cons, 4),
                    horizon_months=horizon_months,
                )
                rec: PlanningRecommendation = self.engine.recommend(p_in)
                results.append(
                    {
                        "decision_date": decision_date.isoformat(),
                        "item_code": itm.item_code,
                        "godown": gdw.godown_name,
                        "current_stock": avail_stock,
                        "incoming_stock": simulated_incoming_stock,
                        "lead_time_days": p_in.lead_time_days,
                        "action": rec.action,
                        "recommended_order_qty": rec.recommended_order_qty,
                        "recommended_transfer_in": rec.recommended_transfer_in,
                        "recommended_transfer_out": rec.recommended_transfer_out,
                        "recommended_hold_qty": rec.recommended_hold_qty,
                        "order_date": rec.order_date.isoformat() if rec.order_date else None,
                        "expected_arrival_date": rec.expected_arrival_date.isoformat() if rec.expected_arrival_date else None,
                        "explanation": rec.explanation,
                    }
                )
        return results