"""Intent classification and entity extraction using Gemini."""

import json
import httpx
from google import genai
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
            # Corporate proxy injects self-signed certs; disable SSL verification.
            # URL, headers, timeout are passed per-request by the SDK, so this is safe.
            _client._api_client._httpx_client = httpx.Client(verify=False)
    return _client


def parse_intent(message: str) -> dict:
    """
    Parse user message into intent + entities using Gemini.
    Returns: {"intent": str, "entities": dict}
    """
    client = _get_client()
    prompt = INTENT_PARSE_PROMPT.format(message=message)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )

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
        # Fallback: treat entire message as general intent
        parsed = {"intent": "general", "entities": {}}

    # Ensure structure
    if "intent" not in parsed:
        parsed["intent"] = "general"
    if "entities" not in parsed:
        parsed["entities"] = {}

    return parsed
