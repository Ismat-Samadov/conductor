"""Intent classification and entity extraction using Gemini."""

import re
import json
import time
import httpx
from google import genai
from google.genai.errors import ClientError
from conductor.config import GEMINI_API_KEY, MODEL_NAME, DISABLE_SSL_VERIFY
from conductor.rag.prompts import INTENT_PARSE_PROMPT


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options={"api_version": "v1beta"},
        )
        if DISABLE_SSL_VERIFY:
            _client._api_client._httpx_client = httpx.Client(verify=False)
    return _client


# ── Local pre-parser (saves Gemini calls for obvious intents) ──

_BUS_NUMBER_RE = re.compile(
    r"^(?:#?\s*)?(\d{1,3}[a-zA-Z]?)\s*(?:nömrəli|nomreli|nomerli)?\s*(?:avtobus)?\s*(?:haqqında|haqqinda|məlumat|melumat)?\.?$",
    re.IGNORECASE,
)
_ROUTE_KEYWORDS = ("necə gedim", "nece gedim", "hansı avtobus", "hansi avtobus", "getmək", "getmek", "gedə bilərəm", "gede bilerem")
_NEARBY_KEYWORDS = ("yaxınlıq", "yaxinliq", "yaxında", "yaxinda", "dayanacaq var", "ən yaxın", "en yaxin")
_GREETING_KEYWORDS = ("salam", "hello", "hi", "merhaba")
_LOCATION_WORDS = ("buradan", "burdan", "burada", "bura", "məndən", "menden", "mənə yaxın", "mene yaxin")


def _local_parse(message: str) -> dict | None:
    """Try to classify intent locally without calling Gemini. Returns None if unsure."""
    m = message.strip().lower()

    # Greeting
    if m in _GREETING_KEYWORDS or m.rstrip("!") in _GREETING_KEYWORDS:
        return {"intent": "general", "entities": {}}

    # Bus number pattern: "3", "#65", "108A nömrəli avtobus"
    bus_match = _BUS_NUMBER_RE.match(m)
    if bus_match:
        return {"intent": "bus_info", "entities": {"bus_number": bus_match.group(1)}}

    # Nearby stops
    if any(kw in m for kw in _NEARBY_KEYWORDS):
        return {"intent": "nearby_stops", "entities": {}}

    # Route finding: "X-dan Y-a necə gedim?"
    if any(kw in m for kw in _ROUTE_KEYWORDS):
        origin = "user_location"
        destination = m

        # Try "X-dan/dən ... necə/hansı" (two-point route)
        route_match = re.search(r"(.+?)(?:dan|dən)\s+(.+?)\s+(?:necə|nece|hansı|hansi)", m)
        if route_match:
            origin = route_match.group(1).strip()
            destination = route_match.group(2).strip()
        else:
            # Try "... necə gedim / hansı avtobus gedir" (single destination)
            dest_match = re.search(r"(.+?)\s+(?:necə|nece|hansı|hansi)", m)
            if dest_match:
                destination = dest_match.group(1).strip()

        # Detect "buradan"/"burdan" as user_location
        if any(w in origin for w in _LOCATION_WORDS):
            origin = "user_location"

        return {"intent": "route_find", "entities": {"origin": origin, "destination": destination}}

    return None  # not sure — fall through to Gemini


# ── Main parser ──

def parse_intent(message: str) -> dict:
    """
    Parse user message into intent + entities.
    Tries local parsing first, falls back to Gemini.
    """
    # Try local parsing first (no API call)
    local = _local_parse(message)
    if local is not None:
        return local

    # Fall back to Gemini with retry on rate limit
    return _parse_with_gemini(message)


def _parse_with_gemini(message: str, retries: int = 1) -> dict:
    """Parse intent via Gemini, with one retry on rate limit."""
    client = _get_client()
    prompt = INTENT_PARSE_PROMPT.format(message=message)

    for attempt in range(1 + retries):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
            )
            break
        except ClientError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(15)
                continue
            raise

    text = response.text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {"intent": "general", "entities": {}}

    if "intent" not in parsed:
        parsed["intent"] = "general"
    if "entities" not in parsed:
        parsed["entities"] = {}

    return parsed
