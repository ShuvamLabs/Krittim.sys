from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import sys
from typing import Callable, Dict, List, Optional, Tuple
import pandas as pd


@dataclass(frozen=True)
class PlanningInput:
    item_code: str
    godown_name: str
    decision_date: date
    lead_time_days: int
    current_godown_stock: float
    incoming_stock: float
    historical_consumption_to_date: float
    recent_monthly_consumption: float
    horizon_months: int = 1


@dataclass(frozen=True)
class PlanningRecommendation:
    action: str  # "ORDER" | "HOLD" | "REDUCE" | "TRANSFER" | "TRANSFER_IN" | "TRANSFER_OUT" | "OK"
    recommended_order_qty: float
    recommended_transfer_in: float = 0.0
    recommended_transfer_out: float = 0.0
    recommended_hold_qty: float = 0.0
    order_date: Optional[date] = None
    expected_arrival_date: Optional[date] = None
    explanation: str = ""


class RecommendationEngineAdapter:
    """Adapter around Shuvam's run_ordering_planner (or a custom callable) with
    a deterministic fallback when no external planner is available.
    """

    def __init__(
        self,
        custom_fn: Optional[Callable[[PlanningInput], PlanningRecommendation]] = None,
        planner_dir: Optional[Path] = None,
        lookback_months: int = 3,
        safety_buffer: float = 0.15,
        hold_multiplier: float = 1.50,
    ) -> None:
        self._custom_fn = custom_fn
        self.planner_dir = planner_dir
        self.lookback_months = lookback_months
        self.safety_buffer = safety_buffer
        self.hold_multiplier = hold_multiplier
        self._planner_cache: Optional[pd.DataFrame] = None

    def load_shuvam_planner_df(self, src_dir: Optional[Path] = None) -> Optional[pd.DataFrame]:
        """Calls Shuvam's run_ordering_planner if src/ordering_planner.py is on disk,
        or falls back to reading backend_ready/ordering_recommendations.csv.
        """
        base = src_dir or self.planner_dir
        if base is None:
            # Default layout when backend/ and backend_ready/ sit under project root
            here = Path(__file__).resolve().parents[2]
            candidates = [here.parent / "src", here.parent.parent / "src"]
            base = next((c for c in candidates if (c / "ordering_planner.py").exists()), None)

        if base is not None and (base / "ordering_planner.py").exists():
            if str(base) not in sys.path:
                sys.path.insert(0, str(base))
            import ordering_planner  # type: ignore

            orders_df, _ = ordering_planner.run_ordering_planner(
                lookback_months=self.lookback_months,
                safety_buffer=self.safety_buffer,
                hold_multiplier=self.hold_multiplier,
            )
            self._planner_cache = orders_df
            return orders_df

        # Fallback to precomputed ordering_recommendations.csv if present
        here = Path(__file__).resolve().parents[2]
        csv_candidates = [
            here.parent / "backend_ready" / "ordering_recommendations.csv",
            here.parent.parent / "backend_ready" / "ordering_recommendations.csv",
        ]
        for csv_p in csv_candidates:
            if csv_p.exists():
                df = pd.read_csv(csv_p)
                self._planner_cache = df
                return df
        return None

    def recommend(self, payload: PlanningInput) -> PlanningRecommendation:
        if self._custom_fn is not None:
            rec = self._custom_fn(payload)
        else:
            # Check if cached planner DataFrame has an entry matching (godown, item_code, date <= decision_date)
            if self._planner_cache is not None and not self._planner_cache.empty:
                df = self._planner_cache
                sub = df[
                    (df["godown"].astype(str).str.strip() == payload.godown_name.strip())
                    & (df["item_code"].astype(str).str.strip() == payload.item_code.strip())
                    & (pd.to_datetime(df["date"]).dt.date <= payload.decision_date)
                ].sort_values("date")
                if not sub.empty:
                    row = sub.iloc[-1]
                    raw_action = str(row.get("action", "HOLD")).strip().upper()
                    # Normalize TRANSFER_IN / TRANSFER_OUT to TRANSFER if caller expects TRANSFER,
                    # while keeping exact info in explanation
                    action = "TRANSFER" if raw_action in ("TRANSFER_IN", "TRANSFER_OUT", "TRANSFER") else raw_action
                    if action not in ("ORDER", "HOLD", "REDUCE", "TRANSFER", "OK"):
                        action = "HOLD"
                    order_qty = max(0.0, float(row.get("recommended_order_qty", 0.0) or 0.0))
                    lt = max(0, int(payload.lead_time_days))
                    order_dt = payload.decision_date if action == "ORDER" and order_qty > 0 else None
                    arr_dt = (payload.decision_date + timedelta(days=lt)) if order_dt else None
                    return PlanningRecommendation(
                        action=action,
                        recommended_order_qty=order_qty,
                        recommended_transfer_in=float(row.get("recommended_transfer_in", 0.0) or 0.0),
                        recommended_transfer_out=float(row.get("recommended_transfer_out", 0.0) or 0.0),
                        recommended_hold_qty=float(row.get("recommended_hold_qty", 0.0) or 0.0),
                        order_date=order_dt,
                        expected_arrival_date=arr_dt,
                        explanation=f"Shuvam planner ({raw_action}) as of {row.get('date')}: target={row.get('lead_time_target_stock')}.",
                    )

            projected_demand = max(0.0, payload.recent_monthly_consumption * max(1, payload.horizon_months))
            cover = payload.current_godown_stock + payload.incoming_stock
            if cover < projected_demand:
                order_qty = round(projected_demand - cover, 4)
                lt = max(0, int(payload.lead_time_days))
                rec = PlanningRecommendation(
                    action="ORDER",
                    recommended_order_qty=order_qty,
                    order_date=payload.decision_date,
                    expected_arrival_date=payload.decision_date + timedelta(days=lt),
                    explanation=f"Projected demand ({projected_demand:.2f}) exceeds stock+incoming ({cover:.2f}) over {lt}d lead time.",
                )
            elif cover > projected_demand * 2.5 and payload.current_godown_stock > 0:
                rec = PlanningRecommendation(
                    action="REDUCE",
                    recommended_order_qty=0.0,
                    order_date=None,
                    expected_arrival_date=None,
                    explanation=f"Stock cover ({cover:.2f}) is high relative to projected demand ({projected_demand:.2f}); slow/hold orders.",
                )
            else:
                rec = PlanningRecommendation(
                    action="HOLD",
                    recommended_order_qty=0.0,
                    order_date=None,
                    expected_arrival_date=None,
                    explanation="Current stock and incoming pipeline cover projected demand.",
                )
            return rec

        if rec.recommended_order_qty < 0:
            raise ValueError("recommended_order_qty cannot be negative")
        return rec
