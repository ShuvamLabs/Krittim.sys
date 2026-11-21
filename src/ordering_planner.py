from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "backend_ready"

def run_ordering_planner(
    lookback_months: int = 3,
    safety_buffer: float = 0.15,
    hold_multiplier: float = 1.50,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    items = pd.read_csv(OUT / "items.csv")
    inv = pd.read_csv(OUT / "inventory_summary.csv")
    cons = pd.read_csv(OUT / "consumption.csv")

    df = (
        inv.merge(cons, on=["date", "godown", "item_code"], how="left")
        .merge(items[["item_code", "lead_time_days", "role"]], on="item_code", how="left")
    )
    df["qty_consumed"] = df["qty_consumed"].fillna(0.0)
    df = df.sort_values(["godown", "item_code", "date"]).reset_index(drop=True)

    # Trailing rolling consumption using only data known up to that month
    df["rolling_monthly_consumption"] = (
        df.groupby(["godown", "item_code"])["qty_consumed"]
        .transform(lambda s: s.rolling(lookback_months, min_periods=1).mean())
    )

    # Target stock required to cover lead time + safety buffer
    lead_months = df["lead_time_days"] / 30.0
    df["lead_time_target_stock"] = df["rolling_monthly_consumption"] * lead_months * (1.0 + safety_buffer)
    df["hold_threshold"] = df["lead_time_target_stock"] * hold_multiplier

    # Raw surplus / deficit before inter-godown balancing
    df["raw_deficit"] = (df["lead_time_target_stock"] - df["stock"]).clip(lower=0.0)
    df["transferable_surplus"] = np.where(
        df["godown"] != "KANPUR CLOSER",
        (df["stock"] - df["hold_threshold"]).clip(lower=0.0),
        0.0,
    )

    # Greedy inter-godown transfer matching per (date, item_code)
    transfer_records = []
    net_transfer_in = np.zeros(len(df))
    net_transfer_out = np.zeros(len(df))

    for (dt, item_code), grp in df.groupby(["date", "item_code"]):
        surplus_rows = grp[grp["transferable_surplus"] > 1e-3].sort_values("transferable_surplus", ascending=False)
        deficit_rows = grp[grp["raw_deficit"] > 1e-3].sort_values("raw_deficit", ascending=False)

        if surplus_rows.empty or deficit_rows.empty:
            continue

        sup_rem = surplus_rows["transferable_surplus"].to_dict()
        def_rem = deficit_rows["raw_deficit"].to_dict()

        for d_idx in deficit_rows.index:
            for s_idx in surplus_rows.index:
                if def_rem[d_idx] <= 1e-3:
                    break
                if sup_rem[s_idx] <= 1e-3:
                    continue

                move_qty = min(def_rem[d_idx], sup_rem[s_idx])
                def_rem[d_idx] -= move_qty
                sup_rem[s_idx] -= move_qty
                net_transfer_in[d_idx] += move_qty
                net_transfer_out[s_idx] += move_qty

                transfer_records.append({
                    "date": dt,
                    "item_code": item_code,
                    "item_name": df.loc[d_idx, "item_name"],
                    "unit": df.loc[d_idx, "unit"],
                    "from_godown": df.loc[s_idx, "godown"],
                    "to_godown": df.loc[d_idx, "godown"],
                    "transfer_qty": round(move_qty, 3),
                })

    df["recommended_transfer_in"] = net_transfer_in
    df["recommended_transfer_out"] = net_transfer_out
    df["recommended_order_qty"] = (df["raw_deficit"] - df["recommended_transfer_in"]).clip(lower=0.0)
    df["recommended_hold_qty"] = (df["stock"] - df["recommended_transfer_out"] - df["hold_threshold"]).clip(lower=0.0)

    # Primary action classification
    conditions = [
        df["recommended_order_qty"] > 1e-3,
        df["recommended_transfer_in"] > 1e-3,
        df["recommended_transfer_out"] > 1e-3,
        df["recommended_hold_qty"] > 1e-3,
    ]
    choices = ["ORDER", "TRANSFER_IN", "TRANSFER_OUT", "HOLD"]
    df["action"] = np.select(conditions, choices, default="OK")

    order_cols = [
        "date", "godown", "item_code", "item_name", "unit", "role", "lead_time_days",
        "stock", "qty_consumed", "rolling_monthly_consumption", "lead_time_target_stock",
        "action", "recommended_order_qty", "recommended_transfer_in",
        "recommended_transfer_out", "recommended_hold_qty",
    ]
    orders_out = df[order_cols].round(3)
    transfers_out = pd.DataFrame(transfer_records)

    orders_out.to_csv(OUT / "ordering_recommendations.csv", index=False)
    transfers_out.to_csv(OUT / "transfer_recommendations.csv", index=False)

    print("Ordering Planner complete!")
    print("Action breakdown:\n", orders_out["action"].value_counts())
    print(f"Total inter-godown transfer suggestions: {len(transfers_out)}")
    return orders_out, transfers_out

if __name__ == "__main__":
    run_ordering_planner()