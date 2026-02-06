"""
Graph ingestion script — loads stops.json and busDetails.json into Neo4j.

Usage:
    python scripts/build_graph.py
"""

import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conductor.graph.client import Neo4jClient
from conductor.config import TRANSFER_MAX_DISTANCE_METERS

DATA_DIR = os.path.join(os.path.dirname(os.path.
dirname(os.path.abspath(__file__))), "data")


def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_name(name: str) -> str:
    if not name:
        return ""
    return name.strip().lower()


def safe_float(val, default=0.0) -> float:
    """Parse float from potentially dirty data (e.g., '40,578,409' → 40.578409)."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return default
    # If string has commas, check if it's a malformed coordinate (e.g., "40,578,409")
    if "," in s and "." not in s:
        # Likely "40,578409" or "40,578,409" — first part is integer, rest is decimal
        parts = s.split(",")
        if len(parts) >= 2:
            s = parts[0] + "." + "".join(parts[1:])
    try:
        return float(s)
    except ValueError:
        return default


# ──────────────────────────────────────────────
# Phase 0: Constraints & Indexes
# ──────────────────────────────────────────────

def create_constraints_and_indexes(client: Neo4jClient):
    print("Creating constraints and indexes...")

    statements = [
        "CREATE CONSTRAINT stop_id IF NOT EXISTS FOR (s:Stop) REQUIRE s.id IS UNIQUE",
        "CREATE CONSTRAINT bus_id IF NOT EXISTS FOR (b:Bus) REQUIRE b.id IS UNIQUE",
        "CREATE CONSTRAINT carrier_name IF NOT EXISTS FOR (c:Carrier) REQUIRE c.name IS UNIQUE",
        "CREATE CONSTRAINT zone_id IF NOT EXISTS FOR (z:Zone) REQUIRE z.id IS UNIQUE",
        "CREATE INDEX stop_name IF NOT EXISTS FOR (s:Stop) ON (s.nameNormalized)",
        "CREATE INDEX bus_number IF NOT EXISTS FOR (b:Bus) ON (b.number)",
        "CREATE POINT INDEX stop_location IF NOT EXISTS FOR (s:Stop) ON (s.location)",
    ]

    for stmt in statements:
        try:
            client.run_write(stmt)
        except Exception as e:
            # Some constraints may already exist
            if "already exists" not in str(e).lower() and "equivalent" not in str(e).lower():
                print(f"  Warning: {e}")
    print("  Done.\n")


# ──────────────────────────────────────────────
# Phase 1: Stop nodes
# ──────────────────────────────────────────────

def ingest_stops(client: Neo4jClient, bus_details: list):
    """
    Create Stop nodes from busDetails (which has names, codes, coords).
    busDetails stops are the richest source — each bus.stops[].stop has full info.
    """
    print("Ingesting Stop nodes...")

    # Collect unique stops from all bus details
    stops_map = {}
    for bus in bus_details:
        for bus_stop in bus.get("stops", []):
            stop = bus_stop.get("stop")
            if not stop or not stop.get("id"):
                continue
            sid = stop["id"]
            if sid not in stops_map:
                stops_map[sid] = {
                    "id": sid,
                    "code": stop.get("code", ""),
                    "name": stop.get("name", ""),
                    "nameNormalized": normalize_name(stop.get("name", "")),
                    "latitude": safe_float(stop.get("latitude")),
                    "longitude": safe_float(stop.get("longitude")),
                    "isTransportHub": stop.get("isTransportHub", False),
                }

    stops_list = list(stops_map.values())
    print(f"  Found {len(stops_list)} unique stops.")

    # Batch upsert in chunks
    batch_size = 200
    for i in range(0, len(stops_list), batch_size):
        batch = stops_list[i : i + batch_size]
        client.run_write(
            """
            UNWIND $stops AS s
            MERGE (stop:Stop {id: s.id})
            SET stop.code = s.code,
                stop.name = s.name,
                stop.nameNormalized = s.nameNormalized,
                stop.latitude = s.latitude,
                stop.longitude = s.longitude,
                stop.isTransportHub = s.isTransportHub,
                stop.location = point({latitude: s.latitude, longitude: s.longitude})
            """,
            {"stops": batch},
        )
        print(f"  Stops: {min(i + batch_size, len(stops_list))}/{len(stops_list)}")

    print(f"  Created {len(stops_list)} Stop nodes.\n")
    return stops_map


# ──────────────────────────────────────────────
# Phase 2: Carrier & Zone nodes
# ──────────────────────────────────────────────

def ingest_carriers_and_zones(client: Neo4jClient, bus_details: list):
    print("Ingesting Carrier and Zone nodes...")

    carriers = set()
    zones = {}

    for bus in bus_details:
        carrier = bus.get("carrier")
        if carrier:
            carriers.add(carrier)

        wzt = bus.get("workingZoneType")
        if wzt and wzt.get("id"):
            zones[wzt["id"]] = wzt.get("name", "")

    # Carriers
    client.run_write(
        """
        UNWIND $carriers AS name
        MERGE (c:Carrier {name: name})
        """,
        {"carriers": list(carriers)},
    )
    print(f"  Created {len(carriers)} Carrier nodes.")

    # Zones
    zone_list = [{"id": k, "name": v} for k, v in zones.items()]
    client.run_write(
        """
        UNWIND $zones AS z
        MERGE (zone:Zone {id: z.id})
        SET zone.name = z.name
        """,
        {"zones": zone_list},
    )
    print(f"  Created {len(zone_list)} Zone nodes.\n")


# ──────────────────────────────────────────────
# Phase 3: Bus nodes + OPERATED_BY + IN_ZONE
# ──────────────────────────────────────────────

def ingest_buses(client: Neo4jClient, bus_details: list):
    print("Ingesting Bus nodes...")

    bus_list = []
    for bus in bus_details:
        bus_list.append({
            "id": bus["id"],
            "number": bus.get("number", ""),
            "carrier": bus.get("carrier", ""),
            "firstPoint": bus.get("firstPoint", ""),
            "lastPoint": bus.get("lastPoint", ""),
            "routLength": bus.get("routLength", 0),
            "durationMinuts": bus.get("durationMinuts", 0),
            "tariff": bus.get("tariff", 0),
            "tariffStr": bus.get("tariffStr", ""),
            "paymentType": bus.get("paymentType", {}).get("name", ""),
            "region": bus.get("region", {}).get("name", ""),
            "zoneId": bus.get("workingZoneType", {}).get("id", 0),
            "zoneName": bus.get("workingZoneType", {}).get("name", ""),
        })

    batch_size = 100
    for i in range(0, len(bus_list), batch_size):
        batch = bus_list[i : i + batch_size]
        client.run_write(
            """
            UNWIND $buses AS b
            MERGE (bus:Bus {id: b.id})
            SET bus.number = b.number,
                bus.carrier = b.carrier,
                bus.firstPoint = b.firstPoint,
                bus.lastPoint = b.lastPoint,
                bus.routLength = b.routLength,
                bus.durationMinuts = b.durationMinuts,
                bus.tariff = b.tariff,
                bus.tariffStr = b.tariffStr,
                bus.paymentType = b.paymentType,
                bus.region = b.region,
                bus.zoneName = b.zoneName
            """,
            {"buses": batch},
        )

    print(f"  Created {len(bus_list)} Bus nodes.")

    # OPERATED_BY
    client.run_write(
        """
        UNWIND $buses AS b
        MATCH (bus:Bus {id: b.id})
        MATCH (carrier:Carrier {name: b.carrier})
        MERGE (bus)-[:OPERATED_BY]->(carrier)
        """,
        {"buses": bus_list},
    )
    print("  Created OPERATED_BY relationships.")

    # IN_ZONE
    client.run_write(
        """
        UNWIND $buses AS b
        MATCH (bus:Bus {id: b.id})
        MATCH (zone:Zone {id: b.zoneId})
        MERGE (bus)-[:IN_ZONE]->(zone)
        """,
        {"buses": bus_list},
    )
    print("  Created IN_ZONE relationships.\n")


# ──────────────────────────────────────────────
# Phase 4: HAS_STOP relationships
# ──────────────────────────────────────────────

def ingest_has_stop(client: Neo4jClient, bus_details: list):
    print("Ingesting HAS_STOP relationships...")

    total = 0
    batch = []
    batch_size = 500

    for bus in bus_details:
        bus_id = bus["id"]
        stops = bus.get("stops", [])

        # Group by direction and sort by sequence (the 'id' field acts as ordering)
        dir_stops = {}
        for bs in stops:
            d = bs.get("directionTypeId", 1)
            if d not in dir_stops:
                dir_stops[d] = []
            dir_stops[d].append(bs)

        for direction, d_stops in dir_stops.items():
            d_stops.sort(key=lambda x: x["id"])
            for order, bs in enumerate(d_stops):
                stop_id = bs.get("stopId")
                if not stop_id:
                    continue
                batch.append({
                    "busId": bus_id,
                    "stopId": stop_id,
                    "order": order,
                    "direction": direction,
                    "distanceFromStart": bs.get("totalDistance", 0),
                    "intermediateDistance": bs.get("intermediateDistance", 0),
                })
                total += 1

                if len(batch) >= batch_size:
                    _flush_has_stop(client, batch)
                    batch = []

    if batch:
        _flush_has_stop(client, batch)

    print(f"  Created {total} HAS_STOP relationships.\n")


def _flush_has_stop(client: Neo4jClient, batch: list):
    client.run_write(
        """
        UNWIND $rels AS r
        MATCH (bus:Bus {id: r.busId})
        MATCH (stop:Stop {id: r.stopId})
        MERGE (bus)-[h:HAS_STOP {direction: r.direction, order: r.order}]->(stop)
        SET h.distanceFromStart = r.distanceFromStart,
            h.intermediateDistance = r.intermediateDistance
        """,
        {"rels": batch},
    )


# ──────────────────────────────────────────────
# Phase 5: NEXT_STOP relationships
# ──────────────────────────────────────────────

def ingest_next_stop(client: Neo4jClient, bus_details: list):
    print("Ingesting NEXT_STOP relationships...")

    total = 0
    batch = []
    batch_size = 500

    for bus in bus_details:
        bus_id = bus["id"]
        bus_number = bus.get("number", "")
        stops = bus.get("stops", [])

        dir_stops = {}
        for bs in stops:
            d = bs.get("directionTypeId", 1)
            if d not in dir_stops:
                dir_stops[d] = []
            dir_stops[d].append(bs)

        for direction, d_stops in dir_stops.items():
            d_stops.sort(key=lambda x: x["id"])
            for i in range(len(d_stops) - 1):
                from_id = d_stops[i].get("stopId")
                to_id = d_stops[i + 1].get("stopId")
                if not from_id or not to_id:
                    continue
                dist = abs(
                    (d_stops[i + 1].get("intermediateDistance", 0))
                    - (d_stops[i].get("intermediateDistance", 0))
                )
                batch.append({
                    "fromId": from_id,
                    "toId": to_id,
                    "busId": bus_id,
                    "busNumber": bus_number,
                    "direction": direction,
                    "distance": round(dist, 2),
                })
                total += 1

                if len(batch) >= batch_size:
                    _flush_next_stop(client, batch)
                    batch = []

    if batch:
        _flush_next_stop(client, batch)

    print(f"  Created {total} NEXT_STOP relationships.\n")


def _flush_next_stop(client: Neo4jClient, batch: list):
    client.run_write(
        """
        UNWIND $rels AS r
        MATCH (a:Stop {id: r.fromId})
        MATCH (b:Stop {id: r.toId})
        MERGE (a)-[n:NEXT_STOP {busId: r.busId, direction: r.direction}]->(b)
        SET n.busNumber = r.busNumber,
            n.distance = r.distance
        """,
        {"rels": batch},
    )


# ──────────────────────────────────────────────
# Phase 6: TRANSFER relationships (proximity)
# ──────────────────────────────────────────────

def ingest_transfers(client: Neo4jClient):
    """
    Create TRANSFER edges between stops that are within TRANSFER_MAX_DISTANCE_METERS
    of each other but do NOT share a direct NEXT_STOP connection on the same bus.
    This is done in Neo4j using the spatial point index.
    """
    print(f"Ingesting TRANSFER relationships (within {TRANSFER_MAX_DISTANCE_METERS}m)...")

    result = client.run_query(
        """
        MATCH (a:Stop), (b:Stop)
        WHERE a.location IS NOT NULL
          AND b.location IS NOT NULL
          AND a.id < b.id
          AND point.distance(a.location, b.location) <= $maxDist
          AND NOT (a)-[:NEXT_STOP]->(b)
          AND NOT (b)-[:NEXT_STOP]->(a)
        WITH a, b, point.distance(a.location, b.location) AS dist
        MERGE (a)-[t:TRANSFER]->(b)
        SET t.walkingDistanceMeters = round(dist, 1),
            t.walkingTimeMinutes = round(dist / 72.0, 1)
        MERGE (b)-[t2:TRANSFER]->(a)
        SET t2.walkingDistanceMeters = round(dist, 1),
            t2.walkingTimeMinutes = round(dist / 72.0, 1)
        RETURN count(t) AS created
        """,
        {"maxDist": TRANSFER_MAX_DISTANCE_METERS},
    )

    count = result[0]["created"] if result else 0
    print(f"  Created {count} TRANSFER pairs (bidirectional).\n")


# ──────────────────────────────────────────────
# Phase 7: Validation
# ──────────────────────────────────────────────

def validate_graph(client: Neo4jClient):
    print("Validating graph...")

    checks = [
        ("Stop nodes", "MATCH (s:Stop) RETURN count(s) AS c"),
        ("Bus nodes", "MATCH (b:Bus) RETURN count(b) AS c"),
        ("Carrier nodes", "MATCH (c:Carrier) RETURN count(c) AS c"),
        ("Zone nodes", "MATCH (z:Zone) RETURN count(z) AS c"),
        ("HAS_STOP rels", "MATCH ()-[r:HAS_STOP]->() RETURN count(r) AS c"),
        ("NEXT_STOP rels", "MATCH ()-[r:NEXT_STOP]->() RETURN count(r) AS c"),
        ("TRANSFER rels", "MATCH ()-[r:TRANSFER]->() RETURN count(r) AS c"),
        ("OPERATED_BY rels", "MATCH ()-[r:OPERATED_BY]->() RETURN count(r) AS c"),
        ("IN_ZONE rels", "MATCH ()-[r:IN_ZONE]->() RETURN count(r) AS c"),
    ]

    for label, query in checks:
        result = client.run_query(query)
        count = result[0]["c"] if result else 0
        print(f"  {label}: {count}")

    # Check orphan stops (stops with no bus)
    orphans = client.run_query(
        "MATCH (s:Stop) WHERE NOT (s)<-[:HAS_STOP]-() RETURN count(s) AS c"
    )
    orphan_count = orphans[0]["c"] if orphans else 0
    if orphan_count > 0:
        print(f"  Warning: {orphan_count} orphan stops (no bus serves them)")

    print("\nGraph build complete.")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def clear_graph(client: Neo4jClient):
    print("Clearing existing graph data...")
    # Delete in batches to avoid memory issues on large graphs
    client.run_write("MATCH ()-[r]->() DELETE r")
    client.run_write("MATCH (n) DELETE n")
    print("  Done.\n")


def main():
    print("=" * 60)
    print("  Conductor — Graph Ingestion")
    print("=" * 60 + "\n")

    # Load data
    print("Loading JSON data...")
    bus_details = load_json("busDetails.json")
    stops_raw = load_json("stops.json")
    print(f"  busDetails.json: {len(bus_details)} buses")
    print(f"  stops.json: {len(stops_raw)} stops\n")

    with Neo4jClient() as client:
        client.verify_connectivity()
        print()

        clear_graph(client)
        create_constraints_and_indexes(client)

        start = time.time()

        ingest_stops(client, bus_details)
        ingest_carriers_and_zones(client, bus_details)
        ingest_buses(client, bus_details)
        ingest_has_stop(client, bus_details)
        ingest_next_stop(client, bus_details)
        ingest_transfers(client)
        validate_graph(client)

        elapsed = time.time() - start
        print(f"\nTotal ingestion time: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
