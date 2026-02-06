"""LLM response generation — takes graph context + user query → Azerbaijani response."""

import httpx
from google import genai
from conductor.config import GEMINI_API_KEY, MODEL_NAME, DISABLE_SSL_VERIFY
from conductor.rag.prompts import (
    SYSTEM_PROMPT,
    ROUTE_CONTEXT_TEMPLATE,
    NO_ROUTE_CONTEXT,
    LOCATION_REQUEST,
)

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


def _format_direct_routes(routes: list[dict]) -> str:
    lines = ["Birbaşa marşrutlar tapıldı:\n"]
    for i, r in enumerate(routes, 1):
        lines.append(
            f"{i}. Avtobus #{r['busNumber']} ({r.get('carrier', '')})\n"
            f"   Min: {r['originStopName']} → Düş: {r['destStopName']}\n"
            f"   Dayanacaq sayı: {r.get('stopCount', '?')}\n"
            f"   Qiymət: {r.get('tariffStr', '?')} | Ödəniş: {r.get('paymentType', '?')}"
        )
    return "\n".join(lines)


def _format_transfer_routes(routes: list[dict]) -> str:
    lines = ["Köçürməli marşrutlar tapıldı:\n"]
    for i, r in enumerate(routes, 1):
        lines.append(
            f"{i}. Avtobus #{r['bus1Number']} → piyada → Avtobus #{r['bus2Number']}\n"
            f"   Min: {r['originStopName']}\n"
            f"   Köçürmə: {r['transferStop1Name']} → {r['transferStop2Name']} "
            f"(piyada ~{r.get('walkingMeters', 0):.0f}m, ~{r.get('walkingMinutes', 0):.0f} dəq)\n"
            f"   Düş: {r['destStopName']}\n"
            f"   Avtobus 1: #{r['bus1Number']} ({r.get('bus1Carrier', '')}) — {r.get('bus1Tariff', '?')}\n"
            f"   Avtobus 2: #{r['bus2Number']} ({r.get('bus2Carrier', '')}) — {r.get('bus2Tariff', '?')}"
        )
    return "\n".join(lines)


def format_route_context(search_result: dict, origin_name: str, dest_name: str) -> str:
    route_type = search_result.get("type", "no_route")
    routes = search_result.get("routes", [])

    if route_type == "direct":
        return _format_direct_routes(routes)
    elif route_type == "one_transfer":
        return _format_transfer_routes(routes)
    else:
        return NO_ROUTE_CONTEXT.format(origin=origin_name, destination=dest_name)


def generate_response(
    user_message: str,
    context: str,
    conversation_history: list[dict] | None = None,
) -> str:
    """
    Generate a response using Gemini with graph context.
    conversation_history: list of {"role": "user"|"model", "parts": [{"text": "..."}]}
    """
    client = _get_client()

    prompt = ROUTE_CONTEXT_TEMPLATE.format(
        context=context, question=user_message
    )

    # Build contents with history
    contents = []
    if conversation_history:
        contents.extend(conversation_history)
    contents.append({"role": "user", "parts": [{"text": prompt}]})

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config=genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,
            max_output_tokens=1024,
        ),
    )

    return response.text.strip()


def generate_simple_response(
    user_message: str,
    context: str,
) -> str:
    """Single-turn response without conversation history."""
    return generate_response(user_message, context)


def ask_for_location() -> str:
    return LOCATION_REQUEST
