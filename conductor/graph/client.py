"""Neo4j client — uses HTTP Query API v2 (port 443) to bypass corporate firewalls."""

import requests
import urllib3
from base64 import b64encode
from conductor.config import NEO4J_HTTP_URL, NEO4J_USERNAME, NEO4J_PASSWORD, DISABLE_SSL_VERIFY

if DISABLE_SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class Neo4jClient:
    def __init__(self):
        self._url = NEO4J_HTTP_URL
        self._auth = (NEO4J_USERNAME, NEO4J_PASSWORD)
        token = b64encode(f"{NEO4J_USERNAME}:{NEO4J_PASSWORD}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def close(self):
        pass  # HTTP is stateless, nothing to close

    def verify_connectivity(self):
        result = self._execute("RETURN 1 AS n")
        if result is not None:
            print(f"Connected to Neo4j via HTTP API at {self._url}")
        else:
            raise ConnectionError(f"Failed to connect to Neo4j at {self._url}")

    def _execute(self, query: str, parameters: dict = None) -> list[dict] | None:
        """Execute a Cypher query via the HTTP Query API v2."""
        payload = {"statement": query}
        if parameters:
            payload["parameters"] = parameters

        resp = requests.post(
            self._url,
            json=payload,
            headers=self._headers,
            timeout=120,
            verify=not DISABLE_SSL_VERIFY,
        )

        if resp.status_code != 200 and resp.status_code != 202:
            error_msg = resp.text[:500]
            raise RuntimeError(
                f"Neo4j HTTP API error {resp.status_code}: {error_msg}"
            )

        body = resp.json()

        # Handle errors in response body
        errors = body.get("errors", [])
        if errors:
            raise RuntimeError(f"Neo4j query error: {errors}")

        # Parse the v2 response format
        data = body.get("data", {})
        fields = data.get("fields", [])
        rows = data.get("values", [])

        if not fields:
            return []

        # Convert to list of dicts
        result = []
        for row in rows:
            record = {}
            for i, field in enumerate(fields):
                record[field] = _extract_value(row[i]) if i < len(row) else None
            result.append(record)

        return result

    def run_query(self, query: str, parameters: dict = None) -> list[dict]:
        result = self._execute(query, parameters)
        return result if result is not None else []

    def run_write(self, query: str, parameters: dict = None):
        return self._execute(query, parameters)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def _extract_value(val):
    """Recursively extract values from Neo4j HTTP API v2 response format."""
    if isinstance(val, dict):
        # Node or relationship objects come as typed wrappers
        if "$type" in val:
            t = val["$type"]
            if t == "Node":
                # Return node properties
                return val.get("_properties", val)
            elif t == "Relationship":
                return val.get("_properties", val)
            elif t == "Point":
                return val
        # Regular dict — recurse
        return {k: _extract_value(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_extract_value(v) for v in val]
    return val
