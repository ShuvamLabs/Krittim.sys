from datetime import date
import pandas as pd


def test_csv_zero_qty_and_godown_mapping():
    items = pd.read_csv("items.csv")
    sets = pd.read_csv("sets.csv")
    rec = pd.read_csv("receipts.csv")
    tr = pd.read_csv("transfers.csv")
    cm = pd.read_csv("contractor_moves.csv")

    assert len(items) == 16
    assert sets["parent_code"].nunique() == 3
    assert set(tr["direction"].dropna().unique()).issubset({"IN", "OUT"})
    assert set(cm["type"].dropna().unique()).issubset({"ISSUE", "CONSUMPTION", "RETURN"})
    assert cm[cm["type"] == "CONSUMPTION"]["godown"].isna().all()
    assert (rec["qty_received"] == 0).sum() == 2
    assert (cm["qty"] == 0).sum() == 2695
