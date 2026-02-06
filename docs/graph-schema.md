# Neo4j Graph Schema

Conductor uses a Neo4j Aura graph database to model the Baku public transportation network. The graph is accessed via the **HTTP Query API v2** over HTTPS port 443.

---

## Nodes

### Stop

Represents a physical bus stop in Baku.

| Property | Type | Indexed | Description |
|---|---|---|---|
| `id` | int | unique constraint | Stop ID from AYNA API |
| `name` | string | | Display name (Azerbaijani) |
| `nameNormalized` | string | btree index | Lowercase name for search |
| `code` | string | | Stop code (e.g., "1002793") |
| `latitude` | float | | WGS84 latitude |
| `longitude` | float | | WGS84 longitude |
| `location` | point | spatial index | Neo4j Point for spatial queries |
| `isTransportHub` | boolean | | Whether it's a major hub (metro, terminal) |

### Bus

Represents a bus route (not an individual vehicle).

| Property | Type | Indexed | Description |
|---|---|---|---|
| `id` | int | unique constraint | Bus route ID from AYNA API |
| `number` | string | btree index | Public-facing number (e.g., "3", "108A") |
| `carrier` | string | | Operating company name |
| `firstPoint` | string | | Route start name |
| `lastPoint` | string | | Route end name |
| `routLength` | float | | Total route length in km |
| `durationMinuts` | int | | Estimated one-way duration |
| `tariff` | int | | Fare in qəpik |
| `tariffStr` | string | | Formatted fare (e.g., "0.60 AZN") |
| `paymentType` | string | | "Kart" or "Nəğd" |

### Carrier

Operating company.

| Property | Type | Description |
|---|---|---|
| `name` | string (unique) | Company name (e.g., "BakuBus MMC") |

### Zone

Working zone classification.

| Property | Type | Description |
|---|---|---|
| `id` | int (unique) | Zone type ID |
| `name` | string | Zone name (e.g., "Şəhərdaxili") |

---

## Relationships

### HAS_STOP

`(Bus)-[HAS_STOP]->(Stop)` — Bus serves this stop.

| Property | Type | Description |
|---|---|---|
| `direction` | int | 1 = outbound, 2 = inbound |
| `order` | int | Position in route sequence (0-based) |
| `distanceFromStart` | float | Distance from route start in km |
| `intermediateDistance` | float | Distance between consecutive stops |

### NEXT_STOP

`(Stop)-[NEXT_STOP]->(Stop)` — Sequential link between adjacent stops on a route.

| Property | Type | Description |
|---|---|---|
| `busId` | int | Bus route that connects them |
| `busNumber` | string | Bus number |
| `direction` | int | Travel direction |
| `distance` | float | Distance between stops |

### TRANSFER

`(Stop)-[TRANSFER]->(Stop)` — Walking transfer between nearby stops (bidirectional).

| Property | Type | Description |
|---|---|---|
| `walkingDistanceMeters` | float | Straight-line distance |
| `walkingTimeMinutes` | float | Estimated walking time (at 72 m/min) |

Created for stop pairs within 300m that don't share a NEXT_STOP edge.

### OPERATED_BY

`(Bus)-[OPERATED_BY]->(Carrier)` — Which company operates the bus.

### IN_ZONE

`(Bus)-[IN_ZONE]->(Zone)` — Which working zone the bus belongs to.

---

## Graph Statistics

| Entity | Count |
|---|---|
| Stop nodes | 3,456 |
| Bus nodes | 208 |
| Carrier nodes | 43 |
| Zone nodes | 7 |
| HAS_STOP relationships | 11,786 |
| NEXT_STOP relationships | 11,357 |
| TRANSFER relationships | 7,492 |
| OPERATED_BY relationships | 208 |
| IN_ZONE relationships | 208 |

---

## Key Query Patterns

### Fuzzy stop search

```cypher
MATCH (s:Stop)
WHERE s.nameNormalized CONTAINS $name
RETURN s.id, s.name, s.latitude, s.longitude
ORDER BY s.isTransportHub DESC, s.name
LIMIT 5
```

### Spatial nearest stops

```cypher
WITH point({latitude: $lat, longitude: $lng}) AS userLoc
MATCH (s:Stop)
WHERE s.location IS NOT NULL
WITH s, point.distance(s.location, userLoc) AS dist
WHERE dist <= $radius
RETURN s.id, s.name, round(dist, 1) AS distanceMeters
ORDER BY dist LIMIT 10
```

### Direct route finding

```cypher
MATCH (origin:Stop)<-[h1:HAS_STOP]-(bus:Bus)-[h2:HAS_STOP]->(dest:Stop)
WHERE origin.id IN $originIds
  AND dest.id IN $destIds
  AND h1.direction = h2.direction
  AND h1.order < h2.order
RETURN bus.number, origin.name, dest.name, h2.order - h1.order AS stopCount
ORDER BY stopCount LIMIT 5
```

### One-transfer route finding

```cypher
MATCH (origin:Stop)<-[h1:HAS_STOP]-(bus1:Bus)-[h2:HAS_STOP]->(ts1:Stop)
MATCH (ts1)-[t:TRANSFER]->(ts2:Stop)
MATCH (ts2)<-[h3:HAS_STOP]-(bus2:Bus)-[h4:HAS_STOP]->(dest:Stop)
WHERE origin.id IN $originIds AND dest.id IN $destIds
  AND bus1.id <> bus2.id
  AND h1.direction = h2.direction AND h1.order < h2.order
  AND h3.direction = h4.direction AND h3.order < h4.order
RETURN bus1.number, bus2.number, ts1.name, ts2.name,
       t.walkingDistanceMeters, dest.name
ORDER BY (h2.order - h1.order) + (h4.order - h3.order)
LIMIT 5
```

---

## Indexes & Constraints

```cypher
-- Constraints
CREATE CONSTRAINT stop_id FOR (s:Stop) REQUIRE s.id IS UNIQUE
CREATE CONSTRAINT bus_id FOR (b:Bus) REQUIRE b.id IS UNIQUE
CREATE CONSTRAINT carrier_name FOR (c:Carrier) REQUIRE c.name IS UNIQUE
CREATE CONSTRAINT zone_id FOR (z:Zone) REQUIRE z.id IS UNIQUE

-- Indexes
CREATE INDEX stop_name FOR (s:Stop) ON (s.nameNormalized)
CREATE INDEX bus_number FOR (b:Bus) ON (b.number)
CREATE POINT INDEX stop_location FOR (s:Stop) ON (s.location)
```
