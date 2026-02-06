"""Cypher query templates for the Conductor Graph RAG."""

# ── Stop lookups ──────────────────────────────────────

FIND_STOPS_BY_NAME = """
MATCH (s:Stop)
WHERE s.nameNormalized CONTAINS $name
RETURN s.id AS id, s.name AS name, s.code AS code,
       s.latitude AS latitude, s.longitude AS longitude,
       s.isTransportHub AS isTransportHub
ORDER BY s.isTransportHub DESC, s.name
LIMIT $limit
"""

FIND_NEAREST_STOPS = """
WITH point({latitude: $lat, longitude: $lng}) AS userLoc
MATCH (s:Stop)
WHERE s.location IS NOT NULL
WITH s, point.distance(s.location, userLoc) AS dist
WHERE dist <= $radius
RETURN s.id AS id, s.name AS name, s.code AS code,
       s.latitude AS latitude, s.longitude AS longitude,
       round(dist, 1) AS distanceMeters
ORDER BY dist
LIMIT $limit
"""

# ── Bus lookups ───────────────────────────────────────

FIND_BUS_BY_NUMBER = """
MATCH (b:Bus)
WHERE b.number = $number
RETURN b.id AS id, b.number AS number, b.carrier AS carrier,
       b.firstPoint AS firstPoint, b.lastPoint AS lastPoint,
       b.routLength AS routLength, b.durationMinuts AS durationMinuts,
       b.tariffStr AS tariffStr, b.paymentType AS paymentType
"""

FIND_BUSES_AT_STOP = """
MATCH (b:Bus)-[:HAS_STOP]->(s:Stop {id: $stopId})
RETURN DISTINCT b.id AS id, b.number AS number, b.carrier AS carrier,
       b.firstPoint AS firstPoint, b.lastPoint AS lastPoint,
       b.tariffStr AS tariffStr, b.paymentType AS paymentType
ORDER BY b.number
"""

# ── Direct route finding ─────────────────────────────

FIND_DIRECT_ROUTES = """
MATCH (origin:Stop)<-[h1:HAS_STOP]-(bus:Bus)-[h2:HAS_STOP]->(dest:Stop)
WHERE origin.id IN $originIds
  AND dest.id IN $destIds
  AND h1.direction = h2.direction
  AND h1.order < h2.order
RETURN bus.id AS busId, bus.number AS busNumber, bus.carrier AS carrier,
       bus.tariffStr AS tariffStr, bus.paymentType AS paymentType,
       bus.durationMinuts AS durationMinuts,
       origin.id AS originStopId, origin.name AS originStopName,
       dest.id AS destStopId, dest.name AS destStopName,
       h1.direction AS direction,
       h2.order - h1.order AS stopCount
ORDER BY stopCount
LIMIT $limit
"""

# ── 1-transfer route finding ─────────────────────────

FIND_ONE_TRANSFER_ROUTES = """
MATCH (origin:Stop)<-[h1:HAS_STOP]-(bus1:Bus)-[h2:HAS_STOP]->(ts1:Stop)
MATCH (ts1)-[t:TRANSFER]->(ts2:Stop)
MATCH (ts2)<-[h3:HAS_STOP]-(bus2:Bus)-[h4:HAS_STOP]->(dest:Stop)
WHERE origin.id IN $originIds
  AND dest.id IN $destIds
  AND bus1.id <> bus2.id
  AND h1.direction = h2.direction
  AND h1.order < h2.order
  AND h3.direction = h4.direction
  AND h3.order < h4.order
RETURN bus1.number AS bus1Number, bus1.carrier AS bus1Carrier,
       bus1.tariffStr AS bus1Tariff,
       bus2.number AS bus2Number, bus2.carrier AS bus2Carrier,
       bus2.tariffStr AS bus2Tariff,
       origin.name AS originStopName,
       ts1.name AS transferStop1Name,
       ts2.name AS transferStop2Name,
       t.walkingDistanceMeters AS walkingMeters,
       t.walkingTimeMinutes AS walkingMinutes,
       dest.name AS destStopName,
       (h2.order - h1.order) + (h4.order - h3.order) AS totalStops
ORDER BY totalStops, t.walkingDistanceMeters
LIMIT $limit
"""

# ── Stop details with all buses ──────────────────────

STOP_DETAIL = """
MATCH (s:Stop {id: $stopId})
OPTIONAL MATCH (b:Bus)-[h:HAS_STOP]->(s)
RETURN s.id AS stopId, s.name AS stopName, s.code AS stopCode,
       s.latitude AS latitude, s.longitude AS longitude,
       s.isTransportHub AS isTransportHub,
       collect(DISTINCT {
           busNumber: b.number,
           busId: b.id,
           carrier: b.carrier,
           firstPoint: b.firstPoint,
           lastPoint: b.lastPoint,
           direction: h.direction
       }) AS buses
"""

# ── Bus route stops (ordered) ────────────────────────

BUS_ROUTE_STOPS = """
MATCH (b:Bus {id: $busId})-[h:HAS_STOP {direction: $direction}]->(s:Stop)
RETURN s.id AS stopId, s.name AS stopName, s.code AS stopCode,
       s.latitude AS latitude, s.longitude AS longitude,
       h.order AS stopOrder, h.distanceFromStart AS distance
ORDER BY h.order
"""
