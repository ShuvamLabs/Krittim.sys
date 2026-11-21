from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class GodownBalanceOut(BaseModel):
    item_code: str
    item_name: str
    unit: str
    godown_name: str
    godown_code: Optional[str] = None
    as_of_date: date
    raw_godown_stock: float
    effective_godown_stock: float
    negative_dip_flagged: bool
    receipts_total: float
    transfers_in_total: float
    transfers_out_total: float
    issues_total: float
    returns_total: float


class ContractorBalanceOut(BaseModel):
    item_code: str
    item_name: str
    unit: str
    as_of_date: date
    issues_total: float
    returns_total: float
    consumption_total: float
    contractor_stock: float


class InventorySummaryOut(BaseModel):
    as_of_date: date
    godown_count: int
    item_count: int
    negative_dip_count: int
    zero_stock_count: int
    balances: List[GodownBalanceOut]


class MovementRecordOut(BaseModel):
    source_table: str
    record_id: int
    date: date
    movement_type: str
    direction: Optional[str] = None
    item_code: str
    item_name: str
    unit: str
    godown_name: Optional[str] = None
    godown_code: Optional[str] = None
    reference_no: Optional[str] = None
    quantity: float


class MovementHistoryOut(BaseModel):
    total: int
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    items: List[MovementRecordOut]


class MonthlyConsumptionPointOut(BaseModel):
    month: str
    item_code: str
    item_name: str
    unit: str
    consumed_qty: float
    cumulative_consumed_qty: float


class ComponentStatusOut(BaseModel):
    child_code: str
    child_name: str
    child_unit: str
    ratio_of_parent: float
    available_godown_qty: float
    required_for_available_parents: float
    max_parents_from_component: Optional[float] = None
    shortage_qty: float
    excess_qty: float


class SetAvailabilityOut(BaseModel):
    set_no: str
    parent_code: str
    parent_name: str
    parent_unit: str
    godown_name: str
    as_of_date: date
    parent_available_qty: float
    complete_sets_possible: int
    limiting_child_code: Optional[str] = None
    is_balanced: bool
    components: List[ComponentStatusOut]
