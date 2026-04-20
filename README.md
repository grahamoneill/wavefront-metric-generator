# Wavefront Synthetic Metric Generator

A lightweight web tool for generating and ingesting synthetic metric data into **VMware Aria Operations for Applications** (formerly Tanzu Observability / Wavefront / DX OpenExplore).

Built for platform engineers and SREs who need to populate dashboards with realistic-looking data before real metrics arrive — useful for demos, dashboard development, and testing alert thresholds.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/react-18-61dafb)](https://reactjs.org/)

---

## Screenshots

![Synthetic Generator](docs/screenshot-generator.png)

![Dashboard Scanner](docs/screenshot-scanner.png)

---

## Features

### ⚡ Synthetic Generator

- Define any number of metric names manually or import them from a dashboard scan
- Auto-generate or manually specify source names and point tag values
- Backfill data as far back as needed (hours + minutes granularity, 5-minute steps)
- Random-walk value generation so charts look like real telemetry, not white noise
- Live point-count estimate with **tiered warnings** — amber at 25k, red hard limit at 50k
- Preview exactly what will be sent (metrics, sources, tags, point count) before confirming
- **Direct ingestion** (HTTPS → tenant) capped at 50,000 points per request
- **Proxy ingestion** (TCP → Wavefront proxy) with automatic pacing for large volumes

### 🔍 Dashboard Scanner

- Fetch any dashboard by its URL slug using your API token
- Extracts every metric name and tag filter across all chart queries, including **disabled intermediate sources** (e.g. metrics used as formula variables like `disk.inodes.used / disk.inodes.total`)
- **NOT filter handling** — queries like `not cpu="cpu-total"` correctly generate synthetic data that satisfies the filter rather than being excluded
- **Per-metric tag scoping** — tags like `cpu` and `fstype` are applied only to the metrics that need them, never polluting unrelated metrics like `disk.free`
- Wildcards (`mem.*`, `swap*`) flagged with an amber warning so you know which metrics need manual attention
- One-click transfer to the Generator — metrics pre-populated with their tag shapes, point tags panel populated with editable rows
- Handles WQL `ts()`, `hs()`, unquoted metric names, OR groups, nested functions, and `querybuilderSerialization` format

### Connection

- Test connection button for both direct and proxy modes before sending data
- Settings persisted across page refreshes (localStorage)
- Shared tenant/token across both tabs

---

## Quickstart — Docker (recommended)

Requires [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/).

```bash
git clone https://github.com/grahamoneill/wavefront-metric-generator.git
cd wavefront-metric-generator
docker compose up --build
```

Open **http://localhost:8080** in your browser.

No Python or Node install required.

---

## Local Development

### Backend (Python 3.11+)

```bash
cd backend
pip install -r requirements.txt
python main.py
# API runs on http://localhost:8001
```

### Frontend (Node 18+)

```bash
cd frontend
npm install
npm run dev
# UI runs on http://localhost:5173
```

The Vite dev server proxies `/api` requests to `localhost:8001` automatically.

---

## Configuration

### Frontend environment

Copy `frontend/.env.example` to `frontend/.env` and set:

```
# Only needed when running the frontend separately pointing at a remote backend
VITE_API_URL=http://my-backend-host:8001
```

In Docker, leave this blank — nginx handles the proxy internally.

### Backend ports

| Service  | Default port | Change in            |
|----------|-------------|----------------------|
| Backend  | 8001        | `docker-compose.yml` |
| Frontend | 8080        | `docker-compose.yml` |

---

## Usage Guide

### Synthetic Generator

1. **Add metrics** — type metric names one per row, or use the **Dashboard Scanner** tab to import from a live dashboard.
2. **Sources** — choose Auto-generate (set a count, default 1) or Manual entry (paste a list).
3. **Point tags** — add tag keys with either auto-generated or specific values. When imported from a scan, tags are pre-populated and scoped per-metric automatically.
4. **Backfill window** — set how far back to generate data (default 5 minutes).
5. **Connection** — select Proxy or Direct, fill in the details, click **Test Connection**.
6. **Preview →** — review metric names, source names, tag values, and exact point count before sending.
7. **Confirm & Send** — data appears in Wavefront within seconds.

**Limits:**
- Direct ingestion: max **50,000 points** per request (hard limit, enforced server-side)
- Warning shown at **25,000 points** — consider reducing backfill window or source count
- Proxy ingestion: no hard limit, automatically paced (1s pause per 50k points)

### Dashboard Scanner

1. Find your dashboard's URL slug — it's the part after `/dashboards/` in the browser URL (e.g. `linux-host`).
2. Enter your tenant URL and API token in the Connection section.
3. Click **Scan Dashboard**.
4. Review the extracted metrics with their full tag shapes.
5. Click **⚡ Send to Generator** — metrics, source, and point tags are pre-populated.
6. Adjust tag values if needed (e.g. change `cpu` from auto-generate to `cpu0, cpu1, cpu2`), then send.

> **Note on wildcards:** Queries like `ts("mem.*", ...)` or `ts("swap*", ...)` cannot be resolved without querying Wavefront itself — these are flagged with an amber warning. Add the specific metric names manually in the Generator.

---

## Architecture

```
wavefront-metric-generator/
├── backend/
│   ├── main.py          # FastAPI app — all API endpoints + WQL parsing
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.jsx      # Full React UI (single file)
│   │   └── main.jsx     # React entry point
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── nginx.conf       # Production nginx config (Docker)
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

### API Endpoints

| Method | Path                      | Description                          |
|--------|---------------------------|--------------------------------------|
| GET    | `/api/health`             | Health check                         |
| POST   | `/api/test-connection`    | Test tenant or proxy connectivity    |
| POST   | `/api/synthetic`          | Send synthetic data                  |
| POST   | `/api/synthetic/estimate` | Estimate point count without sending |
| POST   | `/api/dashboard/scan`     | Fetch dashboard and extract metrics  |

---

## Supported Query Formats

The dashboard scanner parses:

| Format               | Example                                                  |
|----------------------|----------------------------------------------------------|
| WQL quoted           | `ts("my.metric", source="${host}")`                      |
| WQL unquoted         | `ts(my.metric.name, source=${host})`                     |
| WQL histogram        | `hs("my.histogram.m", source="${host}")`                 |
| NOT filters          | `not cpu="cpu-total"` → variable tag `cpu`               |
| Literal filters      | `cpu="cpu-total"` → literal tag sent as-is               |
| Regex tag filters    | `job=/router.*/` → variable tag                          |
| OR groups            | `(task="login" OR task="push")` → separate entries       |
| Disabled sources     | `disabled: true` sources parsed for formula variables    |
| Nested functions     | `aliasSource(taggify(sum(ts(...))))` → drills through    |
| querybuilder format  | Parses `querybuilderSerialization` JSON fallback         |

---

## Contributing

Pull requests welcome. Please:

- Keep backend changes to `backend/main.py` — intentionally a single file
- Keep frontend changes to `frontend/src/App.jsx`
- Run `npm run build` in `frontend/` and `python -c "import main"` in `backend/` before submitting

---

## License

MIT — see [LICENSE](LICENSE).