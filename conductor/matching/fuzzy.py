"""Fuzzy stop name matching — resolves user input to Stop node IDs."""

from conductor.graph.client import Neo4jClient
from conductor.graph import queries
from conductor.matching.aliases import ALIASES
from conductor.matching.transliterate import normalize, generate_variants


class StopMatcher:
    def __init__(self, client: Neo4jClient):
        self.client = client

    def match(self, user_input: str, limit: int = 5) -> list[dict]:
        """
        Resolve user text to a list of candidate stops.
        Tries: alias lookup → exact contains → variant contains.
        Returns list of {id, name, code, latitude, longitude, isTransportHub}.
        """
        text = normalize(user_input)

        # 1. Check aliases first
        search_terms = ALIASES.get(text)
        if search_terms:
            results = []
            for term in search_terms:
                rows = self.client.run_query(
                    queries.FIND_STOPS_BY_NAME,
                    {"name": term, "limit": limit},
                )
                results.extend(rows)
            if results:
                return _dedupe(results, limit)

        # 2. Direct search with normalized input
        results = self.client.run_query(
            queries.FIND_STOPS_BY_NAME,
            {"name": text, "limit": limit},
        )
        if results:
            return results

        # 3. Try all transliteration variants
        for variant in generate_variants(text):
            results = self.client.run_query(
                queries.FIND_STOPS_BY_NAME,
                {"name": variant, "limit": limit},
            )
            if results:
                return results

        return []

    def match_near(
        self, user_input: str, lat: float, lng: float, limit: int = 5
    ) -> list[dict]:
        """
        Match stop name, then sort by distance from user location.
        """
        candidates = self.match(user_input, limit=20)
        if not candidates:
            return []

        # Sort by distance from user
        from math import radians, sin, cos, sqrt, atan2

        def haversine(lat1, lng1, lat2, lng2):
            R = 6371000  # meters
            dlat = radians(lat2 - lat1)
            dlng = radians(lng2 - lng1)
            a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
            return R * 2 * atan2(sqrt(a), sqrt(1 - a))

        for c in candidates:
            c["distanceMeters"] = haversine(
                lat, lng, c.get("latitude", 0), c.get("longitude", 0)
            )

        candidates.sort(key=lambda x: x["distanceMeters"])
        return candidates[:limit]


def _dedupe(results: list[dict], limit: int) -> list[dict]:
    seen = set()
    out = []
    for r in results:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
            if len(out) >= limit:
                break
    return out
