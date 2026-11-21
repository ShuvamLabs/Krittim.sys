from pathlib import Path
import pandas as pd

from app.database.connection import SessionLocal, init_db
from app.integrations.data_pipeline import DataPipelineService

DATA_DIR = Path(__file__).resolve().parent.parent / "backend_ready"


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        pipeline = DataPipelineService(db)

        print("1. Importing items.csv...")
        print(pipeline.import_items_csv(DATA_DIR / "items.csv", batch_id="shuvam_items_v1"))

        print("2. Importing material_sets.csv...")
        print(pipeline.import_sets_csv(DATA_DIR / "material_sets.csv", batch_id="shuvam_sets_v1"))

        print("3. Importing receipts.csv...")
        print(pipeline.import_receipts_csv(DATA_DIR / "receipts.csv", batch_id="shuvam_receipts_v1"))

        print("4. Importing transfers.csv...")
        print(pipeline.import_transfers_csv(DATA_DIR / "transfers.csv", batch_id="shuvam_transfers_v1"))

        print("5. Importing contractor_movements.csv...")
        print(pipeline.import_contractor_movements_csv(DATA_DIR / "contractor_movements.csv", batch_id="shuvam_cm_v1"))

        print("6. Importing derived consumption.csv...")
        cons_df = pd.read_csv(DATA_DIR / "consumption.csv")
        print("Inserted consumption rows:", pipeline.import_derived_consumption(cons_df.to_dict(orient="records")))

        print("7. Importing derived inventory_summary.csv...")
        inv_df = pd.read_csv(DATA_DIR / "inventory_summary.csv")
        print("Upserted inventory_summary rows:", pipeline.import_derived_inventory_summary(inv_df.to_dict(orient="records")))

        print("8. Importing derived material_set_availability.csv...")
        set_avail_df = pd.read_csv(DATA_DIR / "material_set_availability.csv")
        print("Upserted material_set_availability rows:", pipeline.import_derived_set_availability(set_avail_df.to_dict(orient="records")))

        print("Done! All data loaded into lumino_inventory.db.")
    finally:
        db.close()


if __name__ == "__main__":
    main()