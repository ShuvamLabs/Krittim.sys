from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
from sqlalchemy.orm import Session

from app.models.database_models import (
    Consumption,
    ContractorMovement,
    DataQualityLog,
    Godown,
    ImportBatch,
    InventorySummary,
    Item,
    MaterialSet,
    MaterialSetAvailability,
    Receipt,
    SetComponent,
    Transfer,
)


def _parse_date(val: Any) -> date:
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    return pd.to_datetime(str(val).strip()).date()


class DataPipelineService:
    """Ingests cleaned CSVs or record lists from Shuvam's data pipeline into SQLite."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _get_or_create_batch(
        self,
        batch_id: str,
        dataset_identity: str,
        source_file: str,
        rows_read: int,
    ) -> Optional[ImportBatch]:
        existing = self.db.query(ImportBatch).filter(ImportBatch.batch_id == batch_id).first()
        if existing is not None:
            return None
        batch = ImportBatch(
            batch_id=batch_id,
            dataset_identity=dataset_identity,
            source_file=source_file,
            rows_read=rows_read,
        )
        self.db.add(batch)
        self.db.flush()
        return batch

    def _item_map(self) -> Dict[str, Item]:
        return {it.item_code: it for it in self.db.query(Item).all()}

    def _godown_map(self) -> Dict[str, Godown]:
        out: Dict[str, Godown] = {}
        for g in self.db.query(Godown).all():
            out[g.godown_name] = g
            if g.godown_code:
                out[g.godown_code] = g
        return out

    def _get_or_create_godown(self, name_or_code: str, godown_code: Optional[str] = None) -> Godown:
        gmap = self._godown_map()
        key = name_or_code.strip()
        if key in gmap:
            return gmap[key]
        g = Godown(
            godown_code=godown_code.strip() if godown_code else None,
            godown_name=key,
            is_closing_store=("CLOSER" in key.upper() or (godown_code or "").upper() == "KNCLO"),
        )
        self.db.add(g)
        self.db.flush()
        return g

    def import_items_csv(self, csv_path: str | Path, batch_id: str, dataset_identity: str = "lumino") -> Dict[str, Any]:
        df = pd.read_csv(csv_path)
        batch = self._get_or_create_batch(batch_id, dataset_identity, str(csv_path), len(df))
        if batch is None:
            return {"status": "DUPLICATE_BATCH_SKIPPED", "batch_id": batch_id, "inserted": 0}

        imap = self._item_map()
        inserted = 0
        for _, r in df.iterrows():
            code = str(r["item_code"]).strip()
            if code in imap:
                continue
            item = Item(
                item_code=code,
                item_name=str(r["item_name"]).strip(),
                unit=str(r["unit"]).strip(),
                lead_time_days=int(r["lead_time_days"]) if "lead_time_days" in r and pd.notna(r["lead_time_days"]) else None,
                role=str(r["role"]).strip() if "role" in r and pd.notna(r["role"]) else None,
            )
            self.db.add(item)
            self.db.flush()
            imap[code] = item
            inserted += 1

        batch.rows_inserted = inserted
        self.db.commit()
        return {"status": "COMPLETED", "batch_id": batch_id, "rows_read": len(df), "inserted": inserted}

    def import_sets_csv(self, csv_path: str | Path, batch_id: str, dataset_identity: str = "lumino") -> Dict[str, Any]:
        df = pd.read_csv(csv_path)
        batch = self._get_or_create_batch(batch_id, dataset_identity, str(csv_path), len(df))
        if batch is None:
            return {"status": "DUPLICATE_BATCH_SKIPPED", "batch_id": batch_id, "inserted": 0}

        imap = self._item_map()
        group_col = "set_no" if "set_no" in df.columns else ("set_code" if "set_code" in df.columns else None)
        if group_col is None:
            if "parent_code" in df.columns:
                df["_set_key"] = df["parent_code"].astype(str)
                group_col = "_set_key"
            else:
                raise KeyError(f"Missing set identifier column in {csv_path}. Found columns: {list(df.columns)}")

        inserted_components = 0
        for set_no, grp in df.groupby(group_col):
            s_code = str(set_no).strip()
            first = grp.iloc[0]
            p_code = str(first["parent_code"]).strip()
            if p_code not in imap:
                raise ValueError(f"Unknown parent_code in sets: {p_code}")
            p_item = imap[p_code]
            mset = self.db.query(MaterialSet).filter(MaterialSet.set_no == s_code).first()
            if mset is None:
                mset = MaterialSet(
                    set_no=s_code,
                    parent_item_id=p_item.id,
                    parent_name=str(first["parent_name"]).strip() if "parent_name" in first and pd.notna(first["parent_name"]) else p_item.item_name,
                    parent_unit=str(first["parent_unit"]).strip() if "parent_unit" in first and pd.notna(first["parent_unit"]) else p_item.unit,
                )
                self.db.add(mset)
                self.db.flush()
            for _, cr in grp.iterrows():
                c_code = str(cr["child_code"]).strip()
                if c_code not in imap:
                    raise ValueError(f"Unknown child_code in sets: {c_code}")
                c_item = imap[c_code]
                exists = (
                    self.db.query(SetComponent)
                    .filter(
                        SetComponent.material_set_id == mset.id,
                        SetComponent.child_item_id == c_item.id,
                    )
                    .first()
                )
                if not exists:
                    self.db.add(
                        SetComponent(
                            material_set_id=mset.id,
                            child_item_id=c_item.id,
                            child_name=str(cr["child_name"]).strip() if "child_name" in cr and pd.notna(cr["child_name"]) else c_item.item_name,
                            child_unit=str(cr["child_unit"]).strip() if "child_unit" in cr and pd.notna(cr["child_unit"]) else c_item.unit,
                            ratio_of_parent=float(cr["ratio_of_parent"]),
                        )
                    )
                    inserted_components += 1

        batch.rows_inserted = inserted_components
        self.db.commit()
        return {"status": "COMPLETED", "batch_id": batch_id, "rows_read": len(df), "inserted_components": inserted_components}

    def import_receipts_csv(self, csv_path: str | Path, batch_id: str, dataset_identity: str = "lumino") -> Dict[str, Any]:
        df = pd.read_csv(csv_path, parse_dates=["date"])
        batch = self._get_or_create_batch(batch_id, dataset_identity, str(csv_path), len(df))
        if batch is None:
            return {"status": "DUPLICATE_BATCH_SKIPPED", "batch_id": batch_id, "inserted": 0}

        imap = self._item_map()
        inserted = skipped_zero = 0
        objs: List[Receipt] = []
        for idx, r in df.iterrows():
            qty = float(r["qty_received"])
            if qty == 0.0:
                skipped_zero += 1
                self.db.add(
                    DataQualityLog(
                        import_batch_id=batch.id,
                        source_file=str(csv_path),
                        row_index=int(idx),
                        issue_type="ZERO_QTY",
                        severity="INFO",
                        detail="Skipped 0-qty receipt row",
                    )
                )
                continue
            icode = str(r["item_code"]).strip()
            if icode not in imap:
                raise ValueError(f"Unknown item_code in receipts at row {idx}: {icode}")
            gdw = self._get_or_create_godown(str(r["godown"]))
            objs.append(
                Receipt(
                    import_batch_id=batch.id,
                    date=_parse_date(r["date"]),
                    grn_no=str(r["grn_no"]).strip() if "grn_no" in r and pd.notna(r["grn_no"]) else None,
                    item_id=imap[icode].id,
                    godown_id=gdw.id,
                    unit=str(r["unit"]).strip() if "unit" in r and pd.notna(r["unit"]) else imap[icode].unit,
                    qty_received=qty,
                )
            )
            inserted += 1

        self.db.bulk_save_objects(objs)
        batch.rows_inserted = inserted
        batch.rows_skipped_zero = skipped_zero
        batch.rows_flagged = skipped_zero
        self.db.commit()
        return {"status": "COMPLETED", "batch_id": batch_id, "rows_read": len(df), "inserted": inserted, "skipped_zero": skipped_zero}

    def import_transfers_csv(self, csv_path: str | Path, batch_id: str, dataset_identity: str = "lumino") -> Dict[str, Any]:
        df = pd.read_csv(csv_path, parse_dates=["date"])
        batch = self._get_or_create_batch(batch_id, dataset_identity, str(csv_path), len(df))
        if batch is None:
            return {"status": "DUPLICATE_BATCH_SKIPPED", "batch_id": batch_id, "inserted": 0}

        imap = self._item_map()
        inserted = skipped_zero = 0
        objs: List[Transfer] = []
        for idx, r in df.iterrows():
            direction = str(r["direction"]).strip().upper()
            if direction not in ("IN", "OUT"):
                raise ValueError(f"Invalid transfer direction at row {idx}: {direction}")
            qty = float(r["qty"])
            if qty == 0.0:
                skipped_zero += 1
                continue
            icode = str(r["item_code"]).strip()
            if icode not in imap:
                raise ValueError(f"Unknown item_code in transfers at row {idx}: {icode}")
            gcode = str(r["godown_code"]).strip() if "godown_code" in r and pd.notna(r["godown_code"]) else None
            gdw = self._get_or_create_godown(str(r["godown"]), godown_code=gcode)
            objs.append(
                Transfer(
                    import_batch_id=batch.id,
                    date=_parse_date(r["date"]),
                    voucher_no=str(r["voucher_no"]).strip() if "voucher_no" in r and pd.notna(r["voucher_no"]) else None,
                    voucher_type=str(r["voucher_type"]).strip() if "voucher_type" in r and pd.notna(r["voucher_type"]) else None,
                    direction=direction,
                    item_id=imap[icode].id,
                    godown_id=gdw.id,
                    unit=str(r["unit"]).strip() if "unit" in r and pd.notna(r["unit"]) else imap[icode].unit,
                    qty=qty,
                )
            )
            inserted += 1

        self.db.bulk_save_objects(objs)
        batch.rows_inserted = inserted
        batch.rows_skipped_zero = skipped_zero
        self.db.commit()
        return {"status": "COMPLETED", "batch_id": batch_id, "rows_read": len(df), "inserted": inserted, "skipped_zero": skipped_zero}

    def import_contractor_movements_csv(self, csv_path: str | Path, batch_id: str, dataset_identity: str = "lumino") -> Dict[str, Any]:
        df = pd.read_csv(csv_path, parse_dates=["date"])
        batch = self._get_or_create_batch(batch_id, dataset_identity, str(csv_path), len(df))
        if batch is None:
            return {"status": "DUPLICATE_BATCH_SKIPPED", "batch_id": batch_id, "inserted": 0}

        imap = self._item_map()
        inserted = skipped_zero = 0
        objs: List[ContractorMovement] = []
        for idx, r in df.iterrows():
            mtype = str(r["type"]).strip().upper()
            if mtype not in ("ISSUE", "CONSUMPTION", "RETURN"):
                raise ValueError(f"Invalid contractor_movements type at row {idx}: {mtype}")
            qty = float(r["qty"])
            if qty == 0.0:
                skipped_zero += 1
                continue
            icode = str(r["item_code"]).strip()
            if icode not in imap:
                raise ValueError(f"Unknown item_code in contractor_moves at row {idx}: {icode}")
            gdw_id: Optional[int] = None
            if "godown" in r and pd.notna(r["godown"]) and str(r["godown"]).strip() != "":
                gdw_id = self._get_or_create_godown(str(r["godown"])).id
            objs.append(
                ContractorMovement(
                    import_batch_id=batch.id,
                    date=_parse_date(r["date"]),
                    type=mtype,
                    item_id=imap[icode].id,
                    godown_id=gdw_id,
                    unit=str(r["unit"]).strip() if "unit" in r and pd.notna(r["unit"]) else imap[icode].unit,
                    qty=qty,
                )
            )
            inserted += 1

        self.db.bulk_save_objects(objs)
        batch.rows_inserted = inserted
        batch.rows_skipped_zero = skipped_zero
        self.db.commit()
        return {"status": "COMPLETED", "batch_id": batch_id, "rows_read": len(df), "inserted": inserted, "skipped_zero": skipped_zero}

    def import_derived_consumption(self, records: List[Dict[str, Any]]) -> int:
        imap = self._item_map()
        count = 0
        for rec in records:
            icode = str(rec["item_code"]).strip()
            if icode not in imap:
                raise ValueError(f"Unknown item_code in derived consumption: {icode}")
            gdw_id = None
            if rec.get("godown"):
                gdw_id = self._get_or_create_godown(str(rec["godown"])).id
            self.db.add(
                Consumption(
                    date=_parse_date(rec["date"]),
                    item_id=imap[icode].id,
                    godown_id=gdw_id,
                    qty_consumed=float(rec["qty_consumed"]),
                )
            )
            count += 1
        self.db.commit()
        return count

    def import_derived_inventory_summary(self, records: List[Dict[str, Any]]) -> int:
        imap = self._item_map()
        count = 0
        for rec in records:
            icode = str(rec["item_code"]).strip()
            if icode not in imap:
                raise ValueError(f"Unknown item_code in inventory_summary: {icode}")
            gdw = self._get_or_create_godown(str(rec["godown"]))
            dt = _parse_date(rec["date"])
            existing = (
                self.db.query(InventorySummary)
                .filter(
                    InventorySummary.date == dt,
                    InventorySummary.item_id == imap[icode].id,
                    InventorySummary.godown_id == gdw.id,
                )
                .first()
            )
            if existing:
                existing.change = float(rec.get("change", 0.0))
                existing.raw_stock = float(rec.get("raw_stock", 0.0))
                existing.stock = float(rec.get("stock", 0.0))
                existing.item_name = str(rec.get("item_name") or imap[icode].item_name)
                existing.unit = str(rec.get("unit") or imap[icode].unit)
            else:
                self.db.add(
                    InventorySummary(
                        date=dt,
                        item_id=imap[icode].id,
                        godown_id=gdw.id,
                        change=float(rec.get("change", 0.0)),
                        raw_stock=float(rec.get("raw_stock", 0.0)),
                        stock=float(rec.get("stock", 0.0)),
                        item_name=str(rec.get("item_name") or imap[icode].item_name),
                        unit=str(rec.get("unit") or imap[icode].unit),
                    )
                )
            count += 1
        self.db.commit()
        return count

    def import_derived_set_availability(self, records: List[Dict[str, Any]]) -> int:
        count = 0
        for rec in records:
            gdw = self._get_or_create_godown(str(rec["godown"]))
            dt = _parse_date(rec["date"])
            scode = str(rec["set_code"]).strip()
            existing = (
                self.db.query(MaterialSetAvailability)
                .filter(
                    MaterialSetAvailability.date == dt,
                    MaterialSetAvailability.godown_id == gdw.id,
                    MaterialSetAvailability.set_code == scode,
                )
                .first()
            )
            if existing:
                existing.available_sets = float(rec.get("available_sets", 0.0))
            else:
                self.db.add(
                    MaterialSetAvailability(
                        date=dt,
                        godown_id=gdw.id,
                        set_code=scode,
                        available_sets=float(rec.get("available_sets", 0.0)),
                    )
                )
            count += 1
        self.db.commit()
        return count
