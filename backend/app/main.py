from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import consumption, inventory, material_sets, movements, planning, reports
from app.database.connection import init_db

app = FastAPI(
    title="Lumino Industries — Inventory Visibility & Planning API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


app.include_router(inventory.router)
app.include_router(movements.router)
app.include_router(consumption.router)
app.include_router(material_sets.router)
app.include_router(planning.router)
app.include_router(reports.router)
