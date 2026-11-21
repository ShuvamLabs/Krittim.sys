# Lumino Industries — Inventory Visibility and Planning System (Backend)

## Setup & Run
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Run Tests
```bash
pytest
```

## API Docs
Once running, open `http://127.0.0.1:8000/docs` for interactive OpenAPI documentation.

## Deployment

For a Render Web Service configured from the repository root:

- Build Command: `pip install -r backend/requirements.txt`
- Start Command: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

`lumino_inventory.db` is tracked in Git and includes the preloaded inventory
data. The API allows requests from `http://localhost:5173` and HTTPS
`*.vercel.app` frontend origins.
