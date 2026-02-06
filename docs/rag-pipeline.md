# RAG Pipeline

Conductor uses a Graph RAG (Retrieval-Augmented Generation) architecture. User queries are processed through three stages: **Intent Parsing**, **Graph Retrieval**, and **Response Generation**.

---

## Architecture

```
User Message
    |
    v
[1. Intent Parser]  ──  Gemini classifies intent + extracts entities
    |
    v
[2. Graph Retriever] ── Cypher queries fetch relevant subgraph from Neo4j
    |
    v
[3. Response Generator] ── Gemini generates Azerbaijani response with graph context
    |
    v
Chat Response
```

---

## 1. Intent Parser (`conductor/rag/parser.py`)

The parser sends the user message to Gemini with a structured prompt that classifies the intent and extracts entities.

### Supported Intents

| Intent | Triggers | Extracted Entities |
|---|---|---|
| `route_find` | "necə gedim?", "hansı avtobus gedir?" | `origin`, `destination` |
| `bus_info` | "3 nömrəli avtobus", "avtobus haqqında" | `bus_number` |
| `stop_info` | "dayanacaq haqqında", "metro stansiyası" | `stop_name` |
| `nearby_stops` | "yaxınlıqda", "burada dayanacaq var?" | _(none)_ |
| `fare_info` | "qiymət", "neçəyədir?" | `bus_number` |
| `schedule_info` | "vaxt", "neçə dəqiqə?" | `bus_number` |
| `general` | greetings, off-topic | _(none)_ |

### Entity Extraction

- `origin`: Start point. Special value `"user_location"` when user says "buradan" (from here), "mənə yaxın" (near me), etc.
- `destination`: End point as a stop/landmark name
- `bus_number`: Bus route number (e.g., "3", "65", "108A")
- `stop_name`: Stop or station name

### Example

Input: `"Gənclik metrosuna hansı avtobus gedir?"`

Output:
```json
{
  "intent": "route_find",
  "entities": {
    "origin": "user_location",
    "destination": "gənclik metrosu"
  }
}
```

### Error Handling

- If Gemini returns invalid JSON, falls back to `{"intent": "general", "entities": {}}`
- If Gemini returns 429 (rate limit), the error propagates to the chat handler which returns a friendly message

---

## 2. Graph Retriever (`conductor/graph/retriever.py`)

Based on the parsed intent, the retriever executes Cypher queries against Neo4j.

### Retrieval by Intent

| Intent | Retrieval Logic |
|---|---|
| `route_find` | 1. Resolve origin/destination to Stop IDs via fuzzy matching. 2. Try direct routes. 3. Fall back to 1-transfer routes. |
| `bus_info` | Find bus by number, get ordered stop list |
| `stop_info` | Match stop name, get detail with all serving buses |
| `nearby_stops` | Spatial query within 500m of user location |
| `fare_info` | Same as `bus_info` (fare is a bus property) |

### Route Search Strategy

```
1. resolve origin → Stop IDs (fuzzy matching + nearest stops)
2. resolve destination → Stop IDs (fuzzy matching)
3. find_direct_routes(origin_ids, dest_ids)
4. if no direct → find_one_transfer_routes(origin_ids, dest_ids)
5. if nothing found → return "no route" context
```

### Origin Resolution

When `origin = "user_location"`:
- Uses session latitude/longitude
- Finds 5 nearest stops as potential origins

When origin is a name:
- Runs fuzzy matching (aliases + transliteration)
- If user has location, sorts matches by distance

---

## 3. Response Generator (`conductor/rag/generator.py`)

Takes the graph context and generates a natural Azerbaijani response using Gemini.

### System Prompt

The LLM persona is "Conductor" with these rules:
- Always respond in Azerbaijani (mirror user's language if different)
- Use only provided context, never fabricate information
- Show bus numbers, stop names, walking directions
- Show prices in AZN format
- Ask for location if unknown
- Keep responses concise

### Context Formatting

**Direct routes:**
```
Birbaşa marşrutlar tapıldı:
1. Avtobus #3 (BakuBus MMC)
   Min: Gənclik m/st → Düş: 28 May m/st
   Dayanacaq sayı: 8
   Qiymət: 0.60 AZN | Ödəniş: Kart
```

**Transfer routes:**
```
Köçürməli marşrutlar tapıldı:
1. Avtobus #211 → piyada → Avtobus #3
   Min: Əhməd Rəcəbli küçəsi 69
   Köçürmə: Atatürk pr. 98 → Atatürk pr. 117 (piyada ~80m, ~1 dəq)
   Düş: Gənclik m/st
```

### Conversation History

The generator passes conversation history to Gemini for multi-turn context. History is stored in the session as Gemini-compatible format:

```json
[
  {"role": "user", "parts": [{"text": "..."}]},
  {"role": "model", "parts": [{"text": "..."}]}
]
```

---

## LLM Configuration

| Parameter | Value |
|---|---|
| Model | `gemini-2.5-flash` |
| Temperature | 0.3 (low creativity, high accuracy) |
| Max output tokens | 1024 |
| API version | v1beta |

---

## Rate Limiting

The free tier of Gemini allows 5 requests per minute. Each chat message uses 2 Gemini calls (1 parse + 1 generate), so the effective rate is ~2.5 messages/minute. The app handles 429 errors gracefully:

```
"Sorğu limiti aşılıb. Zəhmət olmasa, 1 dəqiqə gözləyin və yenidən cəhd edin."
```
