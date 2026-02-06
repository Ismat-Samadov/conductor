# Deployment Guide

---

## Prerequisites

- Python 3.10+ (local development)
- Docker & Docker Compose (container deployment)
- Neo4j Aura account (free tier: https://neo4j.com/cloud/aura-free/)
- Google Gemini API key (free tier: https://aistudio.google.com/apikey)

---

## Local Development

### 1. Clone and set up environment

```bash
git clone <repo-url>
cd conductor
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your Neo4j Aura and Gemini credentials
```

Required variables:

| Variable | Description |
|---|---|
| `NEO4J_HTTP_URL` | Neo4j Aura HTTP API endpoint |
| `NEO4J_USERNAME` | Neo4j username (usually `neo4j`) |
| `NEO4J_PASSWORD` | Neo4j password |
| `GEMINI_API_KEY` | Google Gemini API key |
| `MODEL_NAME` | Gemini model (default: `gemini-2.5-flash`) |

Optional:

| Variable | Default | Description |
|---|---|---|
| `APP_PORT` | 8000 | Server port |
| `DEFAULT_SEARCH_RADIUS_METERS` | 500 | Nearby stops radius |
| `TRANSFER_MAX_DISTANCE_METERS` | 300 | Max walking distance for transfers |
| `DISABLE_SSL_VERIFY` | false | Set to `true` behind corporate proxies |

### 3. Ingest data into Neo4j

```bash
python scripts/build_graph.py
```

This loads `data/busDetails.json` and `data/stops.json` into the Neo4j graph. Takes ~2-3 minutes on Aura free tier.

### 4. Run the server

```bash
uvicorn conductor.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000

---

## Docker Deployment

### Build and run

```bash
docker-compose up --build
```

The `docker-compose.yml` reads from `.env` and exposes port 8000.

### Dockerfile details

- Base image: `python:3.13-slim`
- Copies `conductor/` package (not data/, scripts/, docs/)
- Runs: `uvicorn conductor.main:app --host 0.0.0.0 --port 8000`

### .dockerignore

Excludes `venv/`, `.env`, `data/`, `scripts/`, `docs/`, `.git/` from the build context.

---

## Render Deployment

The app is deployed on Render's free tier at:
**https://conductor-3z8a.onrender.com**

### Setup on Render

1. Create a new **Web Service** connected to your GitHub repo
2. Set **Build Command**: `pip install -r requirements.txt`
3. Set **Start Command**: `uvicorn conductor.main:app --host 0.0.0.0 --port 8000`
4. Add environment variables in the Render dashboard (same as `.env.example`, but **without** `DISABLE_SSL_VERIFY`)
5. Deploy

### Important Notes

- **Cold start**: Free tier instances spin down after 15 minutes of inactivity. First request takes **1-3 minutes** to wake up.
- **No SSL override needed**: Render handles SSL properly, so `DISABLE_SSL_VERIFY` should be `false` or unset.
- **Health check**: Render uses `HEAD /` which returns 200.

---

## Neo4j Aura Setup

1. Sign up at https://neo4j.com/cloud/aura-free/
2. Create a free instance
3. Note the connection URI and password
4. The HTTP API endpoint format is: `https://<instance-id>.databases.neo4j.io/db/neo4j/query/v2`
5. Run `python scripts/build_graph.py` to populate the graph

### Why HTTP API instead of Bolt?

The app uses Neo4j's HTTP Query API v2 (port 443) instead of the Bolt protocol (port 7687). This works in environments where port 7687 may be blocked by firewalls.

---

## Data Refresh

To update the transportation data:

1. Run the scraper scripts to fetch fresh data from AYNA API:
   ```bash
   python scripts/stops.py        # Fetch stops
   python scripts/busDetails.py   # Fetch bus routes
   ```

2. Re-run the graph ingestion:
   ```bash
   python scripts/build_graph.py
   ```

This clears the existing graph and rebuilds it from the JSON files.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| SSL certificate error (corporate network) | Set `DISABLE_SSL_VERIFY=true` in `.env` |
| Port 7687 blocked | Already handled — app uses HTTP API on port 443 |
| Gemini 429 rate limit | Free tier: 5 req/min. App shows friendly message. Wait 1 min. |
| Neo4j connection timeout | Check `NEO4J_HTTP_URL` format and credentials |
| Empty graph (no results) | Run `python scripts/build_graph.py` first |
| Unicode errors on Windows | Set `PYTHONUTF8=1` or use `-X utf8` flag |
