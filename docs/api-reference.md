# API Reference

Base URL: `http://localhost:8000` (local) or `https://conductor-3z8a.onrender.com` (live)

---

## Endpoints

### `GET /`

Serves the main chat UI (Jinja2 template).

**Response:** HTML page

---

### `HEAD /`

Health check endpoint for PaaS platforms (Render, Railway, etc).

**Response:** `200 OK` (empty body)

---

### `POST /api/session/start`

Initialize a new chat session. Optionally provide user coordinates for location-aware routing.

**Request Body:**

```json
{
  "latitude": 40.4093,   // optional
  "longitude": 49.8671   // optional
}
```

**Response:**

```json
{
  "session_id": "uuid-string",
  "greeting": "Salam! Mən Conductor — Bakı avtobus köməkçisiyəm...",
  "nearest_stops": [
    {
      "id": 2666,
      "name": "Y.Çəmənzəminli küç. 123",
      "code": "1002793",
      "latitude": 40.410235,
      "longitude": 49.867118,
      "distanceMeters": 104.1
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `session_id` | string | UUID for all subsequent requests |
| `greeting` | string | Azerbaijani welcome message |
| `nearest_stops` | array | Up to 10 stops within 500m radius (empty if no location) |

---

### `POST /api/session/location`

Update user location for an existing session.

**Request Body:**

```json
{
  "session_id": "uuid-string",
  "latitude": 40.4093,
  "longitude": 49.8671
}
```

**Response:**

```json
{
  "nearest_stops": [...]
}
```

**Errors:** `404` if session not found.

---

### `POST /api/chat`

Send a user message and receive an AI-generated response.

**Request Body:**

```json
{
  "session_id": "uuid-string",
  "message": "Gənclik metrosuna hansı avtobus gedir?"
}
```

**Response:**

```json
{
  "reply": "Gənclik m/st-na çatmaq üçün...",
  "intent": "route_find",
  "routes": [
    {
      "bus1Number": "211",
      "bus1Carrier": "BakuBus MMC",
      "bus1Tariff": "0.65 AZN",
      "bus2Number": "3",
      "bus2Carrier": "BakuBus MMC",
      "bus2Tariff": "0.60 AZN",
      "originStopName": "Əhməd Rəcəbli küçəsi 69",
      "transferStop1Name": "Atatürk prospekti 98",
      "transferStop2Name": "Atatürk prospekti 117",
      "walkingMeters": 80.4,
      "walkingMinutes": 1.1,
      "destStopName": "Gənclik m/st"
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `reply` | string | LLM-generated Azerbaijani response |
| `intent` | string | Detected intent (see below) |
| `routes` | array | Structured route data for map rendering |

**Supported Intents:**

| Intent | Description | Example |
|---|---|---|
| `route_find` | Route between two points | "Gənclik metrosuna necə gedim?" |
| `bus_info` | Info about a specific bus | "3 nömrəli avtobus" |
| `stop_info` | Info about a specific stop | "28 May dayanacağı" |
| `nearby_stops` | Stops near user location | "Yaxınlıqda dayanacaq var?" |
| `fare_info` | Fare/pricing question | "Qiymət nə qədərdir?" |
| `schedule_info` | Schedule/duration question | "Neçə dəqiqə çəkir?" |
| `general` | General conversation | "Salam" |
| `error` | Rate limit or server error | _(automatic)_ |

**Errors:** `404` if session not found. Rate limit (429 from Gemini) returns a friendly Azerbaijani message instead of 500.

---

### `GET /api/stops/nearby`

Find stops near a coordinate.

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `lat` | float | required | Latitude |
| `lng` | float | required | Longitude |
| `radius` | int | 500 | Search radius in meters |

**Response:**

```json
{
  "stops": [
    {
      "id": 2666,
      "name": "Y.Çəmənzəminli küç. 123",
      "code": "1002793",
      "latitude": 40.410235,
      "longitude": 49.867118,
      "distanceMeters": 104.1
    }
  ]
}
```

---

### `GET /api/bus/{number}`

Get bus details and ordered stop list.

**Path Parameters:** `number` (string) — bus number (e.g., "3", "108A")

**Response:**

```json
{
  "bus": {
    "id": 3,
    "number": "3",
    "carrier": "BakuBus MMC",
    "firstPoint": "Dərnəgül m/st",
    "lastPoint": "Badamdar qəs.",
    "routLength": 38.8,
    "durationMinuts": 64,
    "tariffStr": "0.60 AZN",
    "paymentType": "Kart"
  },
  "stops": [
    {
      "stopId": 100,
      "stopName": "Dərnəgül m/st",
      "stopCode": "1000001",
      "latitude": 40.42,
      "longitude": 49.85,
      "stopOrder": 0,
      "distance": 0
    }
  ]
}
```

**Errors:** `404` if bus not found.

---

## Error Handling

| HTTP Code | Scenario | Response |
|---|---|---|
| 200 | Success | JSON response body |
| 404 | Session/bus not found | `{"detail": "..."}` |
| 500 | Unhandled server error | `Internal Server Error` |
| _(handled)_ | Gemini rate limit (429) | Returns friendly message in `reply` field |
