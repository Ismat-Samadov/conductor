# Conductor — Graph RAG System Design

## 1. System Overview

Conductor is a Graph RAG (Retrieval-Augmented Generation) application for Baku public transportation. It allows Azerbaijani-speaking users to ask natural language questions about bus routes, stops, and navigation — and receive accurate, context-aware answers powered by a graph database and an LLM.

### Core User Experience

1. Session starts — system prompts user for their current location (or auto-detects via browser geolocation)
2. User asks a question in Azerbaijani (e.g., _"Gənclik metrosuna hansı avtobus gedir?"_)
3. System retrieves relevant subgraph from the transportation network
4. LLM generates a natural, conversational answer with route options, stop names, transfers, and walking directions

### Target Users

- Azerbaijani-speaking residents and visitors in Baku
- Primary language: **Azerbaijani (az)**
- Fallback language: Russian, English
- Interface: chat-based (web or mobile)

---

## 2. Data Sources

All data is sourced from the AYNA (Azerbaijan Road Transport Agency) API at `map-api.ayna.gov.az`.

### 2.1 Bus Routes (`data/busDetails.json`)

~208 bus routes with full detail:

| Field | Type | Description |
|---|---|---|
| `id` | int | Unique route ID |
| `number` | string | Public-facing bus number (e.g., "210", "108A") |
| `carrier` | string | Operating company (e.g., "BakuBus MMC") |
| `firstPoint` | string | Route start name |
| `lastPoint` | string | Route end name |
| `routLength` | float | Route length in km |
| `durationMinuts` | int | Estimated trip duration |
| `tariff` | int | Fare in qəpik (60 = 0.60 AZN) |
| `paymentTypeId` | int | 1 = Card (Kart), 2 = Cash (Nəğd) |
| `regionId` | int | 1 = Bakı |
| `workingZoneTypeId` | int | 1 = Şəhərdaxili (Urban), 5 = etc. |
| `stops[]` | array | Ordered stop list per direction |
| `routes[]` | array | Polyline coordinates per direction |

Each `stops[]` entry contains:
- `stopId`, `stopName`, `stopCode`
- `directionTypeId`: 1 = outbound (firstPoint → lastPoint), 2 = inbound
- `totalDistance`, `intermediateDistance`
- Nested `stop` object with `latitude`, `longitude`

Each `routes[]` entry contains:
- `directionTypeId`: 1 = outbound, 2 = inbound
- `flowCoordinates[]`: array of `{lat, lng}` for map rendering

### 2.2 Stops (`data/stops.json`)

~3,841 stops with geographic coordinates:

| Field | Type | Description |
|---|---|---|
| `id` | int | Unique stop ID |
| `code` | string | Official stop code |
| `name` | string | Stop name in Azerbaijani |
| `longitude` | string | Geographic longitude |
| `latitude` | string | Geographic latitude |
| `isTransportHub` | bool | Major transfer point flag |

---

## 3. Graph Database Design

### 3.1 Technology

**Neo4j Aura** (cloud) — native graph database with Cypher query language. Chosen for:
- Natural fit for transportation network topology
- Efficient shortest-path and traversal algorithms (Dijkstra, A*)
- Built-in spatial indexing for geo queries
- Connected via **HTTP Query API v2** (`/db/neo4j/query/v2`) over HTTPS port 443 to bypass corporate firewall restrictions on Bolt port 7687

### 3.2 Node Types

```
(:Stop {
    id: INT,
    code: STRING,
    name: STRING,
    latitude: FLOAT,
    longitude: FLOAT,
    isTransportHub: BOOLEAN,
    nameNormalized: STRING        // lowercase, accent-stripped for search
})

(:Bus {
    id: INT,
    number: STRING,
    carrier: STRING,
    firstPoint: STRING,
    lastPoint: STRING,
    routLength: FLOAT,
    durationMinuts: INT,
    tariff: INT,
    tariffStr: STRING,
    paymentType: STRING,          // "Kart" or "Nəğd"
    region: STRING,               // "Bakı"
    workingZoneType: STRING       // "Şəhərdaxili"
})

(:Carrier {
    name: STRING
})

(:Zone {
    id: INT,
    name: STRING                  // "Şəhərdaxili", "Şəhərkənarı", etc.
})
```

### 3.3 Relationship Types

```
// Stop sequence along a bus route (ordered, directional)
(:Bus)-[:HAS_STOP {
    order: INT,                   // sequence position (0-based)
    direction: INT,               // 1 = outbound, 2 = inbound
    distanceFromStart: FLOAT,     // km from route start
    intermediateDistance: FLOAT    // km from previous stop
}]->(:Stop)

// Sequential connection between adjacent stops on a route
(:Stop)-[:NEXT_STOP {
    busId: INT,
    busNumber: STRING,
    direction: INT,
    distance: FLOAT               // km between these two stops
}]->(:Stop)

// Transfer connection: walkable between nearby stops (different routes)
(:Stop)-[:TRANSFER {
    walkingDistanceMeters: FLOAT,
    walkingTimeMinutes: FLOAT
}]->(:Stop)

// Bus operated by carrier
(:Bus)-[:OPERATED_BY]->(:Carrier)

// Bus belongs to zone
(:Bus)-[:IN_ZONE]->(:Zone)
```

### 3.4 Key Indexes

```cypher
CREATE INDEX stop_name FOR (s:Stop) ON (s.nameNormalized);
CREATE INDEX stop_id FOR (s:Stop) ON (s.id);
CREATE POINT INDEX stop_location FOR (s:Stop) ON (s.location);
CREATE INDEX bus_number FOR (b:Bus) ON (b.number);
CREATE INDEX bus_id FOR (b:Bus) ON (b.id);
```

### 3.5 Spatial Index

Each Stop node also stores a Neo4j `point` property for spatial queries:

```cypher
SET s.location = point({latitude: 40.4093, longitude: 49.8671})
```

This enables:
- "Find stops within 500m of me" → `point.distance(s.location, $userLocation) < 500`
- Nearest-stop lookups for origin/destination resolution

### 3.6 Transfer Detection Logic

Two stops are considered walkable transfers if:
- They belong to **different bus routes**
- They are within **300 meters** of each other (configurable)
- Estimated walking time = distance / 1.2 m/s (average walking speed)

```cypher
MATCH (a:Stop), (b:Stop)
WHERE a.id <> b.id
  AND point.distance(a.location, b.location) < 300
  AND NOT EXISTS {
    MATCH (bus:Bus)-[:HAS_STOP]->(a)
    MATCH (bus)-[:HAS_STOP]->(b)
  }
CREATE (a)-[:TRANSFER {
    walkingDistanceMeters: point.distance(a.location, b.location),
    walkingTimeMinutes: point.distance(a.location, b.location) / 72.0
}]->(b)
```

---

## 4. Graph Construction Pipeline

### 4.1 Steps

```
[AYNA API] → [scripts/stops.py] → data/stops.json ─┐
[AYNA API] → [scripts/busDetails.py] → data/busDetails.json ─┤
                                                              ▼
                                              [scripts/build_graph.py]
                                                              │
                                                              ▼
                                                    [Neo4j Database]
```

### 4.2 build_graph.py Responsibilities

1. **Load JSON data** from `data/stops.json` and `data/busDetails.json`
2. **Create Stop nodes** — deduplicate by `stopId`, set coordinates and normalized names
3. **Create Bus nodes** — one per route, flatten nested payment/region/zone into properties
4. **Create Carrier nodes** — deduplicate by name
5. **Create Zone nodes** — deduplicate by id
6. **Create HAS_STOP relationships** — ordered, per direction, from busDetails `stops[]`
7. **Create NEXT_STOP relationships** — between consecutive stops in each direction
8. **Create OPERATED_BY relationships** — bus → carrier
9. **Create IN_ZONE relationships** — bus → zone
10. **Create TRANSFER relationships** — spatial proximity query across all stops
11. **Validate graph** — check connectivity, log orphan nodes

### 4.3 Name Normalization

Azerbaijani stop names must be normalized for fuzzy matching:

```
Original:       "28 May m/st"
Normalized:     "28 may m/st"

Original:       "Gənclik m/st"
Normalized:     "gənclik m/st"

Original:       "Neftçilər m/st"
Normalized:     "neftçilər m/st"
```

Rules:
- Lowercase
- Preserve Azerbaijani characters (ə, ş, ç, ö, ü, ğ, ı)
- Keep abbreviations (m/st = metro stansiyası, qəs. = qəsəbəsi)
- Strip extra whitespace

---

## 5. RAG Architecture

### 5.1 High-Level Flow

```
User Message (az)
       │
       ▼
┌──────────────┐
│  Session Mgr │──── User location (lat/lng) stored in session
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Query Parser │──── Intent classification + entity extraction
└──────┬───────┘
       │
       ▼
┌──────────────────┐
│ Graph Retriever  │──── Cypher query generation → Neo4j → subgraph
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│  LLM Generator   │──── Subgraph context + user query → response (az)
└──────────────────┘
```

### 5.2 Query Parser (Intent + Entity Extraction)

The LLM classifies each user message into an intent and extracts entities.

#### Intents

| Intent | Description | Example |
|---|---|---|
| `route_find` | Find bus(es) between two points | _"Əhmədlidən Gənclik metrosuna necə gedə bilərəm?"_ |
| `bus_info` | Get info about a specific bus number | _"65 nömrəli avtobus harada dayanır?"_ |
| `stop_info` | Get info about a specific stop | _"Gənclik metrosu dayanacağından hansı avtobuslar keçir?"_ |
| `nearby_stops` | Find stops near a location | _"Yaxınlıqda dayanacaq var?"_ |
| `fare_info` | Ask about ticket price | _"210 nömrəli avtobusun qiyməti nə qədərdir?"_ |
| `schedule_info` | Ask about timing/duration | _"88 nömrəli avtobus neçə dəqiqə gedir?"_ |
| `general` | General question about the system | _"BakuBus nədir?"_ |

#### Entities

| Entity | Type | Example |
|---|---|---|
| `origin` | location/stop name | _"Əhmədli"_, _"buradan"_ (= user location) |
| `destination` | location/stop name | _"Gənclik metrosu"_ |
| `bus_number` | string | _"65"_, _"210"_ |
| `stop_name` | string | _"28 May"_ |

**Important:** When origin is _"buradan"_ (from here), _"mənə yaxın"_ (near me), or similar — the system must resolve it to the user's stored coordinates.

### 5.3 Graph Retriever

Converts parsed intent + entities into Cypher queries against Neo4j.

#### Example: `route_find` — "Əhmədlidən Gənclik metrosuna"

**Step 1: Resolve stop names to Stop nodes**

```cypher
// Find origin stops (fuzzy match)
MATCH (s:Stop)
WHERE s.nameNormalized CONTAINS 'əhmədli'
RETURN s
ORDER BY point.distance(s.location, point({latitude: $userLat, longitude: $userLng}))
LIMIT 5

// Find destination stops
MATCH (s:Stop)
WHERE s.nameNormalized CONTAINS 'gənclik'
RETURN s
ORDER BY s.isTransportHub DESC
LIMIT 5
```

**Step 2: Find direct routes**

```cypher
MATCH (origin:Stop)<-[:HAS_STOP {direction: $dir}]-(bus:Bus)-[:HAS_STOP {direction: $dir}]->(dest:Stop)
WHERE origin.id IN $originStopIds
  AND dest.id IN $destStopIds
RETURN bus, origin, dest
```

**Step 3: Find 1-transfer routes (if no direct route)**

```cypher
MATCH (origin:Stop)<-[:HAS_STOP]-(bus1:Bus)-[:HAS_STOP]->(transfer1:Stop)
MATCH (transfer1)-[:TRANSFER]->(transfer2:Stop)
MATCH (transfer2)<-[:HAS_STOP]-(bus2:Bus)-[:HAS_STOP]->(dest:Stop)
WHERE origin.id IN $originStopIds
  AND dest.id IN $destStopIds
RETURN bus1, transfer1, transfer2, bus2, origin, dest
ORDER BY bus1.durationMinuts + bus2.durationMinuts
LIMIT 5
```

**Step 4: Find nearest stops to user location (for walking start)**

```cypher
MATCH (s:Stop)
WHERE point.distance(s.location, point({latitude: $userLat, longitude: $userLng})) < 500
RETURN s
ORDER BY point.distance(s.location, point({latitude: $userLat, longitude: $userLng}))
LIMIT 10
```

### 5.4 LLM Generator

The LLM receives:
- **System prompt**: persona, language rules, formatting guidelines
- **Retrieved subgraph context**: serialized as structured text
- **User message**: original question
- **Session context**: user location, conversation history

#### System Prompt (Core)

```
Sən "Conductor" — Bakı ictimai nəqliyyat köməkçisisən.

Qaydalar:
- Həmişə Azərbaycan dilində cavab ver
- Dəqiq məlumat ver, uydurma etmə
- Avtobus nömrəsini, dayanacaq adlarını və yürüş istiqamətini göstər
- Əgər köçürmə lazımdırsa, köçürmə dayanacağını və piyada məsafəni bildir
- Birbaşa marşrut yoxdursa, bunu açıq bildir və alternativ təklif et
- Qiymət məlumatını AZN ilə göstər
- İstifadəçinin yerini bilmirsənsə, soruş
```

#### Response Format

For route queries, the LLM should respond with:

```
🚌 **65 nömrəli avtobus**
📍 Əhmədli m/st → ... → Gənclik m/st
⏱ ~35 dəqiqə | 💳 0.60 AZN

Əhmədli metro stansiyasının qarşısındakı dayanacaqdan 65 nömrəli avtobusa minin.
Gənclik metro stansiyası dayanacağında düşün.
```

---

## 6. Session & Location Management

### 6.1 Session Start Flow

```
┌───────────────────────────────────┐
│ Session Start                     │
│                                   │
│  1. Request browser geolocation   │
│     ├─ Granted → store coords     │
│     └─ Denied → ask manually:     │
│        "Hazırda haradasınız?"     │
│        (Where are you now?)       │
│                                   │
│  2. Resolve location to nearest   │
│     stops (within 500m)           │
│                                   │
│  3. Greet user:                   │
│     "Salam! Mən Conductor —      │
│      Bakı avtobus köməkçisiyəm.  │
│      Sizə necə kömək edə bilərəm?"│
└───────────────────────────────────┘
```

### 6.2 Session State

```json
{
    "sessionId": "uuid",
    "userLocation": {
        "latitude": 40.4093,
        "longitude": 49.8671,
        "resolvedNearestStops": [
            {"stopId": 1439, "name": "Neftçilər m/st", "distanceMeters": 120}
        ],
        "source": "geolocation | manual | unknown"
    },
    "conversationHistory": [],
    "language": "az"
}
```

### 6.3 Location Resolution

When user says location-relative words:
- _"buradan"_ (from here) → use `userLocation.resolvedNearestStops`
- _"yaxınlıqda"_ (nearby) → spatial query from `userLocation`
- Named place (e.g., _"Əhmədli"_) → fuzzy match against Stop names + well-known landmarks

---

## 7. Fuzzy Name Matching

Users won't type exact stop names. The system needs robust matching.

### 7.1 Common Patterns

| User Input | Actual Stop Name | Strategy |
|---|---|---|
| "gənclik" | "Gənclik m/st" | Contains match |
| "28 may" | "28 May m/st" | Case-insensitive contains |
| "genclik" | "Gənclik m/st" | Transliteration (e→ə) |
| "hezi aslanov" | "Həzi Aslanov m/st" | Transliteration (h→h, e→ə) |
| "icherisheher" | "İçərişəhər m/st" | Transliteration |
| "koroglu" | "Koroğlu m/st" | Transliteration (g→ğ) |

### 7.2 Transliteration Map

Users often type without Azerbaijani special characters:

```
ə ↔ e
ş ↔ sh, s
ç ↔ ch, c
ö ↔ o
ü ↔ u
ğ ↔ g, gh
ı ↔ i
İ ↔ I
```

### 7.3 Alias Dictionary

Well-known landmarks that map to stop names:

```json
{
    "gənclik metrosu": ["Gənclik m/st"],
    "28 may": ["28 May m/st"],
    "sahil metrosu": ["Sahil m/st"],
    "koroğlu metrosu": ["Koroğlu m/st"],
    "əhmədli metrosu": ["Əhmədli m/st"],
    "nərimanov metrosu": ["Nərimanov m/st"],
    "memar əcəmi": ["Memar Əcəmi m/st"],
    "nizami metrosu": ["Nizami m/st"],
    "dərnəgül metrosu": ["Dərnəgül m/st"],
    "həzi aslanov metrosu": ["Həzi Aslanov m/st"],
    "avtovağzal": ["Avtovağzal m/st"],
    "xalqlar dostluğu": ["Xalqlar Dostluğu m/st"],
    "neftçilər metrosu": ["Neftçilər m/st"],
    "ulduz metrosu": ["Ulduz m/st"],
    "bakmil metrosu": ["Bakmil m/st"],
    "içərişəhər metrosu": ["İçərişəhər m/st"]
}
```

---

## 8. Example Query Walkthrough

### User query: _"Buradan Gənclik metrosuna hansı avtobus gedir?"_

**Step 1 — Parse**

```json
{
    "intent": "route_find",
    "origin": { "type": "user_location" },
    "destination": { "type": "stop_name", "value": "gənclik" }
}
```

**Step 2 — Resolve origin**

User location: `(40.4093, 49.8671)` → nearest stops within 500m:
- Stop #1439 "Neftçilər m/st" (120m)
- Stop #1440 "Sahil bağı" (380m)

**Step 3 — Resolve destination**

Fuzzy match "gənclik" → Stop nodes matching `nameNormalized CONTAINS 'gənclik'`:
- Stop #1501 "Gənclik m/st" (isTransportHub: true)

**Step 4 — Find routes**

Cypher finds: Bus #65 passes through both "Neftçilər m/st" and "Gənclik m/st" in direction 1.

**Step 5 — Build context for LLM**

```
Direct route found:
- Bus: #65 (BakuBus MMC)
- Board at: Neftçilər m/st (120m walk from your location)
- Alight at: Gənclik m/st
- Stops in between: 8
- Est. duration: ~20 min
- Fare: 0.60 AZN (Card only)
- Payment: BakıKart
```

**Step 6 — LLM generates response**

> Sizin yaxınlığınızdakı **Neftçilər m/st** dayanacağından **65 nömrəli avtobusa** minə bilərsiniz. Bu avtobus birbaşa **Gənclik m/st** dayanacağına gedir.
>
> 📍 Dayanacağa ~120 metr piyada
> ⏱ Yol müddəti: ~20 dəqiqə
> 💳 Qiymət: 0.60 AZN (yalnız BakıKart)

---

## 9. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Graph DB | **Neo4j Aura** (cloud, HTTP API v2) | Store transportation network |
| Backend | **Python 3.14** | API server, graph queries, LLM orchestration |
| Web Framework | **FastAPI** | REST API |
| LLM | **Google Gemini** (gemini-2.5-flash) | Query parsing, response generation |
| Neo4j Client | **HTTP Query API v2** (requests) | Cypher over HTTPS (port 443) |
| Frontend | **Next.js** or **plain HTML/JS** | Chat UI with map |
| Map | **Mapbox GL** or **Leaflet** | Route visualization |
| Data Pipeline | **Python scripts** | Fetch data from AYNA API, build graph |

### Python Dependencies

```
neo4j              # Neo4j driver (used only for local dev; HTTP API used in prod)
fastapi            # Web framework
uvicorn            # ASGI server
google-genai       # Google Gemini API client
requests           # HTTP client (data fetching + Neo4j HTTP API)
pydantic           # Data validation
python-dotenv      # Environment variables
```

---

## 10. API Design

### 10.1 REST Endpoints

```
POST /api/chat
    Body: { "sessionId": str, "message": str }
    Response: { "reply": str, "routes": [...], "mapData": {...} }

POST /api/session/start
    Body: { "latitude": float, "longitude": float } | {}
    Response: { "sessionId": str, "greeting": str, "nearestStops": [...] }

POST /api/session/location
    Body: { "sessionId": str, "latitude": float, "longitude": float }
    Response: { "nearestStops": [...] }

GET  /api/stops/nearby?lat=40.41&lng=49.87&radius=500
    Response: [{ "id": int, "name": str, "distance": float }]

GET  /api/bus/{number}
    Response: { bus details + stops }
```

### 10.2 WebSocket (Optional)

```
WS /ws/chat/{sessionId}
    → { "type": "message", "text": "..." }
    ← { "type": "reply", "text": "...", "mapData": {...} }
```

---

## 11. Graph Statistics (Actual)

| Metric | Count |
|---|---|
| Stop nodes | 3,456 |
| Bus nodes | 208 |
| Carrier nodes | 43 |
| Zone nodes | 7 |
| HAS_STOP relationships | 11,786 |
| NEXT_STOP relationships | 11,357 |
| TRANSFER relationships | 7,492 (3,746 bidirectional pairs, 300m threshold) |
| OPERATED_BY relationships | 208 |
| IN_ZONE relationships | 208 |

---

## 12. Data Refresh Strategy

```
┌─────────────────────────────────────────┐
│         Nightly Cron (03:00 UTC+4)      │
│                                         │
│  1. Run scripts/stops.py                │
│  2. Run scripts/busDetails.py           │
│  3. Diff new data against existing      │
│  4. Run scripts/build_graph.py          │
│     (incremental update or full rebuild)│
│  5. Log changes, alert on failures      │
└─────────────────────────────────────────┘
```

---

## 13. Directory Structure (Target)

```
conductor/
├── data/
│   ├── busDetails.json
│   └── stops.json
├── docs/
│   ├── busDetails.md
│   ├── stops.md
│   └── system-design.md          ← this file
├── scripts/
│   ├── busDetails.py             # fetch bus data from API
│   ├── stops.py                  # fetch stop data from API
│   └── build_graph.py            # load JSON → Neo4j
├── conductor/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app entry point
│   ├── config.py                 # settings, env vars
│   ├── session.py                # session & location management
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── client.py             # Neo4j connection
│   │   ├── queries.py            # Cypher query templates
│   │   └── retriever.py          # subgraph retrieval logic
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── parser.py             # intent classification + entity extraction
│   │   ├── generator.py          # LLM response generation
│   │   └── prompts.py            # system prompts, templates
│   ├── matching/
│   │   ├── __init__.py
│   │   ├── fuzzy.py              # fuzzy stop name matching
│   │   ├── transliterate.py      # az character normalization
│   │   └── aliases.py            # landmark → stop name map
│   └── api/
│       ├── __init__.py
│       ├── routes.py             # FastAPI route handlers
│       └── models.py             # Pydantic request/response models
├── .env                          # NEO4J_HTTP_URL, GEMINI_API_KEY, etc.
├── .gitignore
├── requirements.txt
└── pyproject.toml
```

---

## 14. Environment Variables

```env
# Neo4j
NEO4J_URI=neo4j+s://<instance-id>.databases.neo4j.io
NEO4J_HTTP_URL=https://<instance-id>.databases.neo4j.io/db/neo4j/query/v2
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=neo4j

# LLM
GEMINI_API_KEY=<key>
MODEL_NAME=gemini-2.5-flash

# App
APP_HOST=0.0.0.0
APP_PORT=8000
DEFAULT_SEARCH_RADIUS_METERS=500
TRANSFER_MAX_DISTANCE_METERS=300
MAX_TRANSFER_COUNT=2
DEFAULT_LANGUAGE=az
```

---

## 15. Constraints & Edge Cases

| Case | Handling |
|---|---|
| No direct route exists | Search 1-transfer, then 2-transfer routes |
| No route found at all | Tell user honestly, suggest taxi or metro |
| User location unknown | Prompt: _"Zəhmət olmasa, hazırda harada olduğunuzu yazın"_ |
| Ambiguous stop name | Return top candidates, ask user to clarify |
| Bus not running (no schedule data) | Note: AYNA API has no live schedule data — state this limitation |
| Multiple buses serve same route | List all options sorted by duration/transfers |
| User types in Russian/English | Detect language, respond accordingly, still query graph in Azerbaijani |
| Stop name has no match | Try transliteration, then ask user to rephrase |
