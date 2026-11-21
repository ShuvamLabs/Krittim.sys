from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.database_models import ContractorMovement, Godown, Item, Receipt, Transfer


@dataclass(frozen=True)
class MovementRecord:
    source_table: str
    record_id: int
    date: date
    movement_type: str
    direction: Optional[str]
    item_code: str
    item_name: str
    unit: str
    godown_name: Optional[str]
    godown_code: Optional[str]
    reference_no: Optional[str]
    quantity: float


class MovementService:
    """Queries and filters historical movement records across receipts,
    contractor movements, and inter-godown transfers.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_movements(
        self,
        item_code: Optional[str] = None,
        godown_name: Optional[str] = None,
        movement_type: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        include_zero_qty: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[int, List[MovementRecord]]:
        records: List[MovementRecord] = []
        mtype_upper = movement_type.upper() if movement_type else None

        if mtype_upper in (None, "RECEIPT"):
            q = (
                self.db.query(Receipt, Item, Godown)
                .join(Item, Receipt.item_id == Item.id)
                .join(Godown, Receipt.godown_id == Godown.id)
            )
            if not include_zero_qty:
                q = q.filter(Receipt.qty_received > 0)
            if item_code:
                q = q.filter(Item.item_code == item_code)
            if godown_name:
                q = q.filter(Godown.godown_name == godown_name)
            if date_from:
                q = q.filter(Receipt.date >= date_from)
            if date_to:
                q = q.filter(Receipt.date <= date_to)

            for rec, itm, gdw in q.all():
                records.append(
                    MovementRecord(
                        source_table="receipts",
                        record_id=rec.id,
                        date=rec.date,
                        movement_type="RECEIPT",
                        direction="IN",
                        item_code=itm.item_code,
                        item_name=itm.item_name,
                        unit=rec.unit,
                        godown_name=gdw.godown_name,
                        godown_code=gdw.godown_code,
                        reference_no=rec.grn_no,
                        quantity=float(rec.qty_received),
                    )
                )

        if mtype_upper in (None, "TRANSFER"):
            q = (
                self.db.query(Transfer, Item, Godown)
                .join(Item, Transfer.item_id == Item.id)
                .join(Godown, Transfer.godown_id == Godown.id)
            )
            if not include_zero_qty:
                q = q.filter(Transfer.qty > 0)
            if item_code:
                q = q.filter(Item.item_code == item_code)
            if godown_name:
                q = q.filter(Godown.godown_name == godown_name)
            if date_from:
                q = q.filter(Transfer.date >= date_from)
            if date_to:
                q = q.filter(Transfer.date <= date_to)

            for tr, itm, gdw in q.all():
                records.append(
                    MovementRecord(
                        source_table="transfers",
                        record_id=tr.id,
                        date=tr.date,
                        movement_type="TRANSFER",
                        direction=tr.direction,
                        item_code=itm.item_code,
                        item_name=itm.item_name,
                        unit=tr.unit,
                        godown_name=gdw.godown_name,
                        godown_code=gdw.godown_code,
                        reference_no=tr.voucher_no,
                        quantity=float(tr.qty),
                    )
                )

        if mtype_upper in (None, "ISSUE", "RETURN", "CONSUMPTION"):
            q = (
                self.db.query(ContractorMovement, Item, Godown)
                .join(Item, ContractorMovement.item_id == Item.id)
                .outerjoin(Godown, ContractorMovement.godown_id == Godown.id)
            )
            if not include_zero_qty:
                q = q.filter(ContractorMovement.qty > 0)
            if mtype_upper in ("ISSUE", "RETURN", "CONSUMPTION"):
                q = q.filter(ContractorMovement.type == mtype_upper)
            if item_code:
                q = q.filter(Item.item_code == item_code)
            if godown_name:
                q = q.filter(Godown.godown_name == godown_name)
            if date_from:
                q = q.filter(ContractorMovement.date >= date_from)
            if date_to:
                q = q.filter(ContractorMovement.date <= date_to)

            for cm, itm, gdw in q.all():
                records.append(
                    MovementRecord(
                        source_table="contractor_movements",
                        record_id=cm.id,
                        date=cm.date,
                        movement_type=cm.type,
                        direction="OUT" if cm.type in ("ISSUE", "CONSUMPTION") else "IN",
                        item_code=itm.item_code,
                        item_name=itm.item_name,
                        unit=cm.unit,
                        godown_name=gdw.godown_name if gdw else None,
                        godown_code=gdw.godown_code if gdw else None,
                        reference_no=None,
                        quantity=float(cm.qty),
                    )
                )

        records.sort(key=lambda r: (r.date, r.source_table, r.record_id))
        total = len(records)
        safe_offset = max(0, offset)
        safe_limit = max(1, limit)
        return total, records[safe_offset : safe_offset + safe_limit]
