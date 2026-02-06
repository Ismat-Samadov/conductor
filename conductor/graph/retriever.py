"""Graph retriever — translates parsed intents into graph queries and returns context."""

from conductor.graph.client import Neo4jClient
from conductor.graph import queries
from conductor.config import DEFAULT_SEARCH_RADIUS_METERS


class GraphRetriever:
    def __init__(self, client: Neo4jClient):
        self.client = client

    # ── Stop resolution ──────────────────────────────

    def find_stops_by_name(self, name: str, limit: int = 5) -> list[dict]:
        normalized = name.strip().lower()
        return self.client.run_query(
            queries.FIND_STOPS_BY_NAME,
            {"name": normalized, "limit": limit},
        )

    def find_nearest_stops(
        self, lat: float, lng: float, radius: int = None, limit: int = 10
    ) -> list[dict]:
        return self.client.run_query(
            queries.FIND_NEAREST_STOPS,
            {
                "lat": lat,
                "lng": lng,
                "radius": radius or DEFAULT_SEARCH_RADIUS_METERS,
                "limit": limit,
            },
        )

    # ── Bus lookups ──────────────────────────────────

    def find_bus_by_number(self, number: str) -> list[dict]:
        return self.client.run_query(
            queries.FIND_BUS_BY_NUMBER, {"number": number}
        )

    def find_buses_at_stop(self, stop_id: int) -> list[dict]:
        return self.client.run_query(
            queries.FIND_BUSES_AT_STOP, {"stopId": stop_id}
        )

    def get_bus_route_stops(self, bus_id: int, direction: int = 1) -> list[dict]:
        return self.client.run_query(
            queries.BUS_ROUTE_STOPS, {"busId": bus_id, "direction": direction}
        )

    # ── Route finding ────────────────────────────────

    def find_direct_routes(
        self, origin_ids: list[int], dest_ids: list[int], limit: int = 5
    ) -> list[dict]:
        return self.client.run_query(
            queries.FIND_DIRECT_ROUTES,
            {"originIds": origin_ids, "destIds": dest_ids, "limit": limit},
        )

    def find_one_transfer_routes(
        self, origin_ids: list[int], dest_ids: list[int], limit: int = 5
    ) -> list[dict]:
        return self.client.run_query(
            queries.FIND_ONE_TRANSFER_ROUTES,
            {"originIds": origin_ids, "destIds": dest_ids, "limit": limit},
        )

    # ── Stop detail ──────────────────────────────────

    def get_stop_detail(self, stop_id: int) -> dict | None:
        rows = self.client.run_query(
            queries.STOP_DETAIL, {"stopId": stop_id}
        )
        return rows[0] if rows else None

    # ── High-level: full route search ────────────────

    def search_routes(
        self,
        origin_ids: list[int],
        dest_ids: list[int],
    ) -> dict:
        """
        Try direct routes first, then 1-transfer.
        Returns structured context for the LLM.
        """
        direct = self.find_direct_routes(origin_ids, dest_ids)
        if direct:
            return {"type": "direct", "routes": direct}

        transfer = self.find_one_transfer_routes(origin_ids, dest_ids)
        if transfer:
            return {"type": "one_transfer", "routes": transfer}

        return {"type": "no_route", "routes": []}
