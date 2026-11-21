from __future__ import annotations

import calendar
import json
from datetime import date
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from app.models.database_models import ContractorMovement, Godown, Item, Receipt, SimulationEvent, SimulationRun
from app.services.planning_service import PlanningService


def _month_end_dates(start_date: date, end_date: date) -> List[date]:
    cur_year, cur_month = start_date.year, start_date.month
    dates: List[date] = []
    while (cur_year, cur_month) <= (end_date.year, end_date.month):
        last_day = calendar.monthrange(cur_year, cur_month)[1]
        d = date(cur_year, cur_month, last_day)
        if d >= start_date:
            dates.append(min(d, end_date))
        if cur_month == 12:
            cur_year += 1
            cur_month = 1
        else:
            cur_month += 1
    return dates


class SimulationService:
    """Replays historical periods month-by-month with strict anti-leakage
    (only transactions with date <= decision_date are visible at decision_date)
    and compares historical actual receipts/stock against simulated orders + lead times.
    """

    def __init__(self, db: Session, planning_service: Optional[PlanningService] = None) -> None:
        self.db = db
        self.planning_service = planning_service or PlanningService(db)

    def run_simulation(
        self,
        name: str,
        start_date: date,
        end_date: date,
        godown_name: Optional[str] = None,
        item_code: Optional[str] = None,
    ) -> dict:
        steps = _month_end_dates(start_date, end_date)
        run = SimulationRun(name=name, start_date=start_date, end_date=end_date, step="monthly")
        self.db.add(run)
        self.db.flush()

        items_q = self.db.query(Item)
        if item_code:
            items_q = items_q.filter(Item.item_code == item_code)
        items = items_q.order_by(Item.item_code).all()

        godowns_q = self.db.query(Godown).filter(Godown.is_closing_store.is_(False))
        if godown_name:
            godowns_q = godowns_q.filter(Godown.godown_name == godown_name)
        godowns = godowns_q.order_by(Godown.godown_name).all()

        hist_total_receipts = 0.0
        sim_total_ordered = 0.0
        sim_order_count = 0
        pipeline_orders: List[dict] = []
        sim_stock: Dict[tuple[str, str], float] = {
            (itm.item_code, gdw.godown_name): 0.0 for itm in items for gdw in godowns
        }

        prev_cutoff: Optional[date] = None
        for step_date in steps:
            still_in_flight = []
            for po in pipeline_orders:
                if po["arrival_date"] <= step_date:
                    key = (po["item_code"], po["godown"])
                    sim_stock[key] = sim_stock.get(key, 0.0) + po["qty"]
                else:
                    still_in_flight.append(po)
            pipeline_orders = still_in_flight

            for itm in items:
                cons_q = self.db.query(ContractorMovement.qty).filter(
                    ContractorMovement.item_id == itm.id,
                    ContractorMovement.type == "CONSUMPTION",
                    ContractorMovement.date <= step_date,
                    ContractorMovement.qty > 0,
                )
                if prev_cutoff is not None:
                    cons_q = cons_q.filter(ContractorMovement.date > prev_cutoff)
                step_cons = float(sum(float(r[0]) for r in cons_q.all()))
                if step_cons > 0 and godowns:
                    per_g = step_cons / len(godowns)
                    for gdw in godowns:
                        key = (itm.item_code, gdw.godown_name)
                        sim_stock[key] = sim_stock.get(key, 0.0) - per_g

                rec_q = self.db.query(Receipt.qty_received).filter(
                    Receipt.item_id == itm.id,
                    Receipt.date <= step_date,
                    Receipt.qty_received > 0,
                )
                if prev_cutoff is not None:
                    rec_q = rec_q.filter(Receipt.date > prev_cutoff)
                if godown_name:
                    gdw_obj = next((g for g in godowns if g.godown_name == godown_name), None)
                    if gdw_obj:
                        rec_q = rec_q.filter(Receipt.godown_id == gdw_obj.id)
                hist_total_receipts += float(sum(float(r[0]) for r in rec_q.all()))

            for itm in items:
                for gdw in godowns:
                    key = (itm.item_code, gdw.godown_name)
                    incoming_qty = sum(
                        p["qty"] for p in pipeline_orders if p["item_code"] == itm.item_code and p["godown"] == gdw.godown_name
                    )
                    recs = self.planning_service.generate_recommendations(
                        decision_date=step_date,
                        godown_name=gdw.godown_name,
                        item_code=itm.item_code,
                        horizon_months=1,
                        simulated_stock_override=max(0.0, sim_stock.get(key, 0.0)),
                        simulated_incoming_stock=incoming_qty,
                    )
                    for r in recs:
                        if r["action"] == "ORDER" and r["recommended_order_qty"] > 0:
                            sim_total_ordered += float(r["recommended_order_qty"])
                            sim_order_count += 1
                            arr_dt = date.fromisoformat(r["expected_arrival_date"])
                            pipeline_orders.append(
                                {
                                    "arrival_date": arr_dt,
                                    "item_code": itm.item_code,
                                    "godown": gdw.godown_name,
                                    "qty": float(r["recommended_order_qty"]),
                                }
                            )
                            self.db.add(
                                SimulationEvent(
                                    run_id=run.id,
                                    event_date=step_date,
                                    event_type="SIMULATED_ORDER",
                                    item_id=itm.id,
                                    godown_id=gdw.id,
                                    quantity=float(r["recommended_order_qty"]),
                                    details_json=json.dumps({"expected_arrival_date": arr_dt.isoformat()}),
                                )
                            )

            prev_cutoff = step_date

        sim_idle_end = round(sum(max(0.0, v) for v in sim_stock.values()), 4)
        summary = {
            "steps_replayed": len(steps),
            "historical_receipts_total": round(hist_total_receipts, 4),
            "simulated_orders_total": round(sim_total_ordered, 4),
            "simulated_order_events": sim_order_count,
            "simulated_ending_positive_stock": sim_idle_end,
            "procurement_qty_delta": round(sim_total_ordered - hist_total_receipts, 4),
        }
        run.summary_json = json.dumps(summary)
        self.db.commit()
        return {"run_id": run.id, "name": run.name, "summary": summary}
