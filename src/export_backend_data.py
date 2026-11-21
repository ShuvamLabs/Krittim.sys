from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
RAW = BASE / "lumino-vch3-data" / "csv"
OUT = BASE / "backend_ready"
OUT.mkdir(parents=True, exist_ok=True)

def clean_str(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.select_dtypes(include=["object", "string"]).columns:
        df[c] = df[c].where(df[c].isna(), df[c].astype(str).str.strip())
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df

# 1. Master & Transaction Tables
items_raw = clean_str(pd.read_csv(RAW / "items.csv"))
sets_raw = clean_str(pd.read_csv(RAW / "sets.csv"))
receipts_raw = clean_str(pd.read_csv(RAW / "receipts.csv"))
transfers_raw = clean_str(pd.read_csv(RAW / "transfers.csv"))
cmoves_raw = clean_str(pd.read_csv(RAW / "contractor_moves.csv", low_memory=False))

items_out = items_raw[["item_code", "item_name", "unit", "lead_time_days", "role"]]
sets_out = sets_raw[["set_no", "parent_code", "child_code", "ratio_of_parent"]].rename(columns={"set_no": "set_code"})
receipts_out = receipts_raw.loc[receipts_raw["qty_received"] > 0, ["date", "item_code", "godown", "qty_received"]]
transfers_out = transfers_raw.loc[transfers_raw["qty"] > 0, ["date", "item_code", "godown", "direction", "qty"]]
cmoves_out = cmoves_raw.loc[cmoves_raw["qty"] > 0, ["date", "type", "item_code", "godown", "qty"]]

items_out.to_csv(OUT / "items.csv", index=False)
sets_out.to_csv(OUT / "material_sets.csv", index=False)
receipts_out.to_csv(OUT / "receipts.csv", index=False)
transfers_out.to_csv(OUT / "transfers.csv", index=False)
cmoves_out.to_csv(OUT / "contractor_movements.csv", index=False)

# 2. Derived Tables (Monthly snapshot dated as YYYY-MM-01)
for df in [receipts_out, transfers_out, cmoves_out]:
    df["month_date"] = pd.to_datetime(df["date"]).dt.to_period("M").dt.to_timestamp().dt.strftime("%Y-%m-%d")

godowns = sorted(set(receipts_out["godown"].dropna()) | set(transfers_out["godown"].dropna()))
item_codes = sorted(items_out["item_code"].unique())
months = sorted(set(receipts_out["month_date"]) | set(transfers_out["month_date"]) | set(cmoves_out["month_date"]))

grid = pd.MultiIndex.from_product([months, godowns, item_codes], names=["date", "godown", "item_code"]).to_frame(index=False)

rec_m = receipts_out.groupby(["month_date", "godown", "item_code"], as_index=False)["qty_received"].sum().rename(columns={"month_date": "date"})
tr_in = transfers_out[transfers_out["direction"] == "IN"].groupby(["month_date", "godown", "item_code"], as_index=False)["qty"].sum().rename(columns={"month_date": "date", "qty": "tr_in"})
tr_out = transfers_out[transfers_out["direction"] == "OUT"].groupby(["month_date", "godown", "item_code"], as_index=False)["qty"].sum().rename(columns={"month_date": "date", "qty": "tr_out"})

cm_g = cmoves_out[cmoves_out["godown"].notna()]
iss_m = cm_g[cm_g["type"] == "ISSUE"].groupby(["month_date", "godown", "item_code"], as_index=False)["qty"].sum().rename(columns={"month_date": "date", "qty": "issued"})
ret_m = cm_g[cm_g["type"] == "RETURN"].groupby(["month_date", "godown", "item_code"], as_index=False)["qty"].sum().rename(columns={"month_date": "date", "qty": "returned"})
cons_p = cmoves_out[cmoves_out["type"] == "CONSUMPTION"].groupby(["month_date", "item_code"], as_index=False)["qty"].sum().rename(columns={"month_date": "date", "qty": "proj_cons"})

inv = (
    grid.merge(rec_m, on=["date", "godown", "item_code"], how="left")
    .merge(tr_in, on=["date", "godown", "item_code"], how="left")
    .merge(tr_out, on=["date", "godown", "item_code"], how="left")
    .merge(iss_m, on=["date", "godown", "item_code"], how="left")
    .merge(ret_m, on=["date", "godown", "item_code"], how="left")
    .merge(cons_p, on=["date", "item_code"], how="left")
    .fillna(0.0)
)

# Derived: consumption (allocated to godowns via net issues)
inv["net_iss"] = (inv["issued"] - inv["returned"]).clip(lower=0.0)
tot_iss = inv.groupby(["date", "item_code"])["net_iss"].transform("sum")
inv["qty_consumed"] = np.where(tot_iss > 0, inv["proj_cons"] * (inv["net_iss"] / tot_iss), inv["proj_cons"] / len(godowns))

consumption_out = inv[["date", "item_code", "godown", "qty_consumed"]].round({"qty_consumed": 3})
consumption_out.to_csv(OUT / "consumption.csv", index=False)

# Derived: inventory_summary
inv["change"] = inv["qty_received"] + inv["tr_in"] + inv["returned"] - inv["tr_out"] - inv["issued"]
inv = inv.sort_values(["godown", "item_code", "date"]).reset_index(drop=True)
inv["raw_stock"] = inv.groupby(["godown", "item_code"])["change"].cumsum()
inv["stock"] = inv["raw_stock"].clip(lower=0.0)
inv = inv.merge(items_out[["item_code", "item_name", "unit"]], on="item_code", how="left")

inventory_summary_out = inv[["date", "item_code", "godown", "change", "raw_stock", "stock", "item_name", "unit"]].round({"change": 3, "raw_stock": 3, "stock": 3})
inventory_summary_out.to_csv(OUT / "inventory_summary.csv", index=False)

# Derived: material_set_availability (bottleneck of parent stock & all required children)
stk = inventory_summary_out[["date", "godown", "item_code", "stock"]]
set_calc = sets_out.merge(stk.rename(columns={"item_code": "parent_code", "stock": "parent_stock"}), on="parent_code")
set_calc = set_calc.merge(stk.rename(columns={"item_code": "child_code", "stock": "child_stock"}), on=["date", "godown", "child_code"])

# Account for shared child MNB010174 demand across sets
set_calc["req_child"] = set_calc["parent_stock"] * set_calc["ratio_of_parent"]
tot_req = set_calc.groupby(["date", "godown", "child_code"])["req_child"].transform("sum")
set_calc["effective_child_stock"] = np.where(tot_req > 0, set_calc["child_stock"] * (set_calc["req_child"] / tot_req), set_calc["child_stock"])
set_calc["max_sets_from_child"] = np.floor(set_calc["effective_child_stock"] / set_calc["ratio_of_parent"])
set_calc["possible_sets"] = np.minimum(np.floor(set_calc["parent_stock"]), set_calc["max_sets_from_child"])

set_avail_out = (
    set_calc.groupby(["date", "godown", "set_code"], as_index=False)["possible_sets"]
    .min()
    .rename(columns={"possible_sets": "available_sets"})
)
set_avail_out.to_csv(OUT / "material_set_availability.csv", index=False)

print("All 8 backend-ready CSVs exported successfully!")