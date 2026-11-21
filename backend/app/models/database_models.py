from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database.connection import Base


class Godown(Base):
    """Normalized godown lookup table supporting both godown name and optional code."""

    __tablename__ = "godowns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    godown_code = Column(String(32), unique=True, nullable=True, index=True)
    godown_name = Column(String(128), unique=True, nullable=False, index=True)
    is_closing_store = Column(Boolean, nullable=False, default=False)

    receipts = relationship("Receipt", back_populates="godown")
    contractor_movements = relationship("ContractorMovement", back_populates="godown")
    transfers = relationship("Transfer", back_populates="godown")


class Item(Base):
    """Master catalog table aligning with Shuvam's schema (item_code, item_name, unit)
    while retaining lead_time_days and role from items.csv for planning and sets.
    """

    __tablename__ = "items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_code = Column(String(64), unique=True, nullable=False, index=True)
    item_name = Column(String(256), nullable=False)
    unit = Column(String(32), nullable=False)
    lead_time_days = Column(Integer, nullable=True)
    role = Column(String(32), nullable=True)

    receipts = relationship("Receipt", back_populates="item")
    contractor_movements = relationship("ContractorMovement", back_populates="item")
    transfers = relationship("Transfer", back_populates="item")
    parent_sets = relationship(
        "MaterialSet",
        back_populates="parent_item",
        foreign_keys="MaterialSet.parent_item_id",
    )
    child_components = relationship(
        "SetComponent",
        back_populates="child_item",
        foreign_keys="SetComponent.child_item_id",
    )


class MaterialSet(Base):
    """Parent-child material set definition."""

    __tablename__ = "material_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    set_no = Column(String(32), unique=True, nullable=False, index=True)
    parent_item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    parent_name = Column(String(256), nullable=False)
    parent_unit = Column(String(32), nullable=False)

    parent_item = relationship(
        "Item",
        back_populates="parent_sets",
        foreign_keys=[parent_item_id],
    )
    components = relationship(
        "SetComponent",
        back_populates="material_set",
        cascade="all, delete-orphan",
    )


class SetComponent(Base):
    """Required child component and ratio per parent unit."""

    __tablename__ = "set_components"
    __table_args__ = (
        UniqueConstraint("material_set_id", "child_item_id", name="uq_set_child"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_set_id = Column(Integer, ForeignKey("material_sets.id"), nullable=False)
    child_item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    child_name = Column(String(256), nullable=False)
    child_unit = Column(String(32), nullable=False)
    ratio_of_parent = Column(Float, nullable=False)

    material_set = relationship("MaterialSet", back_populates="components")
    child_item = relationship(
        "Item",
        back_populates="child_components",
        foreign_keys=[child_item_id],
    )


class ImportBatch(Base):
    """Tracks pipeline import batches for idempotency and auditability."""

    __tablename__ = "import_batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(128), unique=True, nullable=False, index=True)
    dataset_identity = Column(String(128), nullable=False)
    source_file = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="COMPLETED")
    rows_read = Column(Integer, nullable=False, default=0)
    rows_inserted = Column(Integer, nullable=False, default=0)
    rows_skipped_zero = Column(Integer, nullable=False, default=0)
    rows_flagged = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    receipts = relationship("Receipt", back_populates="import_batch")
    contractor_movements = relationship("ContractorMovement", back_populates="import_batch")
    transfers = relationship("Transfer", back_populates="import_batch")
    quality_logs = relationship("DataQualityLog", back_populates="import_batch")


class Receipt(Base):
    """Receipts table aligned with (date, item_code, godown, qty_received) + grn_no/unit."""

    __tablename__ = "receipts"
    __table_args__ = (
        Index("ix_receipts_item_godown_date", "item_id", "godown_id", "date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    import_batch_id = Column(Integer, ForeignKey("import_batches.id"), nullable=True)
    date = Column(Date, nullable=False, index=True)
    grn_no = Column(String(64), nullable=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    godown_id = Column(Integer, ForeignKey("godowns.id"), nullable=False)
    unit = Column(String(32), nullable=True)
    qty_received = Column(Float, nullable=False)

    import_batch = relationship("ImportBatch", back_populates="receipts")
    item = relationship("Item", back_populates="receipts")
    godown = relationship("Godown", back_populates="receipts")


class Transfer(Base):
    """Transfers table aligned with (date, item_code, godown, direction, qty) where
    direction in {'IN', 'OUT'}.
    """

    __tablename__ = "transfers"
    __table_args__ = (
        Index("ix_transfers_item_godown_date_dir", "item_id", "godown_id", "date", "direction"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    import_batch_id = Column(Integer, ForeignKey("import_batches.id"), nullable=True)
    date = Column(Date, nullable=False, index=True)
    voucher_no = Column(String(64), nullable=True)
    voucher_type = Column(String(64), nullable=True)
    direction = Column(String(8), nullable=False, index=True)  # IN | OUT
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    godown_id = Column(Integer, ForeignKey("godowns.id"), nullable=False)
    unit = Column(String(32), nullable=True)
    qty = Column(Float, nullable=False)

    import_batch = relationship("ImportBatch", back_populates="transfers")
    item = relationship("Item", back_populates="transfers")
    godown = relationship("Godown", back_populates="transfers")


class ContractorMovement(Base):
    """Contractor movements table aligned with (date, type, item_code, godown, qty) where
    type in {'ISSUE', 'CONSUMPTION', 'RETURN'} and godown is nullable (blank for CONSUMPTION).
    """

    __tablename__ = "contractor_movements"
    __table_args__ = (
        Index("ix_cm_item_godown_date_type", "item_id", "godown_id", "date", "type"),
        Index("ix_cm_item_date_type", "item_id", "date", "type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    import_batch_id = Column(Integer, ForeignKey("import_batches.id"), nullable=True)
    date = Column(Date, nullable=False, index=True)
    type = Column(String(32), nullable=False, index=True)  # ISSUE | CONSUMPTION | RETURN
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    godown_id = Column(Integer, ForeignKey("godowns.id"), nullable=True)
    unit = Column(String(32), nullable=True)
    qty = Column(Float, nullable=False)

    import_batch = relationship("ImportBatch", back_populates="contractor_movements")
    item = relationship("Item", back_populates="contractor_movements")
    godown = relationship("Godown", back_populates="contractor_movements")


class Consumption(Base):
    """Derived consumption table: (date, item_code, godown, qty_consumed)."""

    __tablename__ = "consumption"
    __table_args__ = (
        Index("ix_consumption_item_godown_date", "item_id", "godown_id", "date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    godown_id = Column(Integer, ForeignKey("godowns.id"), nullable=True)
    qty_consumed = Column(Float, nullable=False)

    item = relationship("Item")
    godown = relationship("Godown")


class InventorySummary(Base):
    """Derived inventory summary table:
    (date, item_code, godown, change, raw_stock, stock, item_name, unit).
    """

    __tablename__ = "inventory_summary"
    __table_args__ = (
        UniqueConstraint("date", "item_id", "godown_id", name="uq_inv_summary_date_item_godown"),
        Index("ix_inv_summary_item_godown_date", "item_id", "godown_id", "date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    godown_id = Column(Integer, ForeignKey("godowns.id"), nullable=False)
    change = Column(Float, nullable=False, default=0.0)
    raw_stock = Column(Float, nullable=False, default=0.0)
    stock = Column(Float, nullable=False, default=0.0)
    item_name = Column(String(256), nullable=False)
    unit = Column(String(32), nullable=False)

    item = relationship("Item")
    godown = relationship("Godown")


class MaterialSetAvailability(Base):
    """Derived material set availability table: (date, godown, set_code, available_sets)."""

    __tablename__ = "material_set_availability"
    __table_args__ = (
        UniqueConstraint("date", "godown_id", "set_code", name="uq_set_avail_date_godown_set"),
        Index("ix_set_avail_godown_date", "godown_id", "date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    godown_id = Column(Integer, ForeignKey("godowns.id"), nullable=False)
    set_code = Column(String(32), nullable=False, index=True)
    available_sets = Column(Float, nullable=False, default=0.0)

    godown = relationship("Godown")


class DataQualityLog(Base):
    """Logs zero-qty rows, out-of-range dates, or suspicious values without dropping data."""

    __tablename__ = "data_quality_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    import_batch_id = Column(Integer, ForeignKey("import_batches.id"), nullable=True)
    source_file = Column(String(128), nullable=False)
    row_index = Column(Integer, nullable=True)
    issue_type = Column(String(64), nullable=False, index=True)
    severity = Column(String(16), nullable=False, default="INFO")
    detail = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    import_batch = relationship("ImportBatch", back_populates="quality_logs")


class SimulationRun(Base):
    """Stores metadata and summary metrics for historical simulation runs."""

    __tablename__ = "simulation_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    step = Column(String(32), nullable=False, default="monthly")
    summary_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    events = relationship(
        "SimulationEvent",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class SimulationEvent(Base):
    """Stores step-by-step events emitted during a historical simulation run."""

    __tablename__ = "simulation_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("simulation_runs.id"), nullable=False)
    event_date = Column(Date, nullable=False, index=True)
    event_type = Column(String(32), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=True)
    godown_id = Column(Integer, ForeignKey("godowns.id"), nullable=True)
    quantity = Column(Float, nullable=False, default=0.0)
    details_json = Column(Text, nullable=True)

    run = relationship("SimulationRun", back_populates="events")
