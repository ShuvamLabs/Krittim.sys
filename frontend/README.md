# Krittim.sys Frontend

## Local development

Start the backend and frontend in separate terminals from the repository root.

PowerShell terminal 1:

```powershell
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

PowerShell terminal 2:

```powershell
cd frontend
$env:VITE_API_BASE_URL = "http://localhost:8000"
npm run dev
```

The dashboard checks the API health endpoint and loads planning recommendations
for the latest bundled recommendation date. If the API is unreachable or returns
an error, the dashboard uses the bundled CSV data in `public/backend_ready/`.

Verify the API from a third terminal:

```powershell
curl.exe -i http://localhost:8000/health
curl.exe -i "http://localhost:8000/planning/recommendations?decision_date=2026-10-01"
```

Both responses should have HTTP status `200`; the health response is
`{"status":"ok"}` and recommendations are a JSON array.

## Production deployment

### Render backend

Create a Web Service for this repository with the repository root as its
directory, then set:

- Build Command: `pip install -r backend/requirements.txt`
- Start Command: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

The SQLite database at `backend/lumino_inventory.db` is tracked in Git and
contains the preloaded data.

### Vercel frontend

Create a Vercel project with **Root Directory** set to `frontend`. Add this
project environment variable, substituting the deployed Render service URL
without a trailing slash:

```text
VITE_API_BASE_URL=https://<your-render-service>.onrender.com
```

Redeploy the frontend after setting or changing the variable. The backend CORS
configuration permits `http://localhost:5173` and HTTPS `*.vercel.app` origins.

After both deployments are live, verify:

```powershell
curl.exe -i https://<your-render-service>.onrender.com/health
curl.exe -i "https://<your-render-service>.onrender.com/planning/recommendations?decision_date=2026-10-01"
```

Open the Vercel site, then use browser developer tools' **Network** panel to
confirm the health check and planning request succeed without CORS errors. The
recommendations request should return `200` and a JSON array.

Build locally with `npm run build`.
