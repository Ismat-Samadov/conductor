"""FastAPI route handlers — the HTTP layer."""

import time
from fastapi import APIRouter, HTTPException
from google.genai.errors import ClientError

from conductor.api.models import (
    SessionStartRequest,
    SessionStartResponse,
    LocationUpdateRequest,
    LocationUpdateResponse,
    ChatRequest,
    ChatResponse,
    NearbyStopsResponse,
)
from conductor.session import Session, SessionStore
from conductor.graph.client import Neo4jClient
from conductor.graph.retriever import GraphRetriever
from conductor.matching.fuzzy import StopMatcher
from conductor.rag.parser import parse_intent
from conductor.rag.generator import (
    generate_response,
    format_route_context,
    ask_for_location,
)
from conductor.rag.prompts import GREETING, GREETING_WITH_LOCATION

router = APIRouter()

# Shared state — initialized in main.py lifespan
neo4j_client: Neo4jClient | None = None
retriever: GraphRetriever | None = None
matcher: StopMatcher | None = None
sessions: SessionStore = SessionStore()


def init_services(client: Neo4jClient):
    global neo4j_client, retriever, matcher
    neo4j_client = client
    retriever = GraphRetriever(client)
    matcher = StopMatcher(client)


# ── Session ─────────────────────────────────────────

@router.post("/api/session/start", response_model=SessionStartResponse)
def start_session(req: SessionStartRequest):
    session = sessions.create()

    if req.latitude is not None and req.longitude is not None:
        session.latitude = req.latitude
        session.longitude = req.longitude
        session.location_source = "geolocation"
        session.nearest_stops = retriever.find_nearest_stops(
            req.latitude, req.longitude
        )
        stop_names = ", ".join(
            s["name"] for s in session.nearest_stops[:3]
        )
        greeting = GREETING_WITH_LOCATION.format(stops=stop_names)
    else:
        greeting = GREETING

    session.add_model_message(greeting)

    return SessionStartResponse(
        session_id=session.id,
        greeting=greeting,
        nearest_stops=session.nearest_stops,
    )


@router.post("/api/session/location", response_model=LocationUpdateResponse)
def update_location(req: LocationUpdateRequest):
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.latitude = req.latitude
    session.longitude = req.longitude
    session.location_source = "manual"
    session.nearest_stops = retriever.find_nearest_stops(
        req.latitude, req.longitude
    )

    return LocationUpdateResponse(nearest_stops=session.nearest_stops)


# ── Chat ────────────────────────────────────────────

@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.add_user_message(req.message)

    try:
        reply, intent, routes = _process_chat(session, req.message)
    except ClientError as e:
        if e.code == 429:
            reply = "Sorğu limiti aşılıb. Zəhmət olmasa, 1 dəqiqə gözləyin və yenidən cəhd edin."
            intent = "error"
            routes = []
        else:
            raise

    session.add_model_message(reply)
    return ChatResponse(reply=reply, intent=intent, routes=routes)


def _last_bot_asked_for_location(session) -> bool:
    """Check if the last bot message was a location request."""
    for msg in reversed(session.conversation_history):
        if msg["role"] == "model":
            text = msg["parts"][0]["text"]
            return "yerinizi bilmirəm" in text or "geolokasiya göndərin" in text
    return False


def _process_chat(session, message: str) -> tuple[str, str, list]:
    """Parse intent and dispatch to handler. May raise ClientError on rate limit."""

    # If bot just asked for location and user responds with a place name,
    # treat it as origin for the pending route search (no Gemini call needed)
    if _last_bot_asked_for_location(session) and session.pending_destination:
        origin_stops = matcher.match(message)
        if origin_stops:
            dest_stops = matcher.match(session.pending_destination)
            if dest_stops:
                origin_ids = [s["id"] for s in origin_stops]
                dest_ids = [s["id"] for s in dest_stops]
                search_result = retriever.search_routes(origin_ids, dest_ids)
                context = format_route_context(
                    search_result, origin_stops[0]["name"], dest_stops[0]["name"]
                )
                reply = generate_response(message, context, session.conversation_history[:-1])
                session.pending_destination = None  # clear after use
                return reply, "route_find", search_result.get("routes", [])

    parsed = parse_intent(message)
    intent = parsed.get("intent", "general")
    entities = parsed.get("entities", {})

    if intent == "route_find":
        reply, routes = _handle_route_find(session, message, entities)
    elif intent == "bus_info":
        reply, routes = _handle_bus_info(message, entities)
    elif intent == "stop_info":
        reply, routes = _handle_stop_info(message, entities)
    elif intent == "nearby_stops":
        reply, routes = _handle_nearby_stops(session, message)
    elif intent in ("fare_info", "schedule_info"):
        reply, routes = _handle_bus_info(message, entities)
    else:
        reply = generate_response(
            message,
            "Ümumi sual. Bakı ictimai nəqliyyat sistemi haqqında cavab ver.",
            session.conversation_history[:-1],
        )
        routes = []

    return reply, intent, routes


# ── Intent handlers ─────────────────────────────────

def _handle_route_find(
    session: Session, message: str, entities: dict
) -> tuple[str, list]:
    origin_raw = entities.get("origin", "")
    dest_raw = entities.get("destination", "")

    # Resolve origin
    if origin_raw == "user_location" or not origin_raw:
        if not session.has_location:
            session.pending_destination = dest_raw
            return ask_for_location(), []
        origin_stops = retriever.find_nearest_stops(
            session.latitude, session.longitude, limit=5
        )
        origin_name = "Sizin yeriniz"
    else:
        origin_stops = matcher.match(origin_raw)
        origin_name = origin_raw
        if session.has_location and origin_stops:
            origin_stops = matcher.match_near(
                origin_raw, session.latitude, session.longitude
            )

    # Resolve destination
    dest_stops = matcher.match(dest_raw)
    dest_name = dest_raw

    if not origin_stops:
        return f"'{origin_name}' adlı dayanacaq tapılmadı. Zəhmət olmasa, daha dəqiq yazın.", []
    if not dest_stops:
        return f"'{dest_name}' adlı dayanacaq tapılmadı. Zəhmət olmasa, daha dəqiq yazın.", []

    origin_ids = [s["id"] for s in origin_stops]
    dest_ids = [s["id"] for s in dest_stops]

    search_result = retriever.search_routes(origin_ids, dest_ids)
    context = format_route_context(search_result, origin_name, dest_name)

    reply = generate_response(
        message, context, session.conversation_history[:-1]
    )

    return reply, search_result.get("routes", [])


def _handle_bus_info(message: str, entities: dict) -> tuple[str, list]:
    bus_number = entities.get("bus_number", "")
    if not bus_number:
        return generate_response(message, "Avtobus nömrəsi göstərilməyib."), []

    buses = retriever.find_bus_by_number(bus_number)
    if not buses:
        return f"#{bus_number} nömrəli avtobus tapılmadı.", []

    bus = buses[0]
    stops = retriever.get_bus_route_stops(bus["id"], direction=1)
    stop_names = " → ".join(s["stopName"] for s in stops)

    context = (
        f"Avtobus #{bus['number']} ({bus.get('carrier', '')})\n"
        f"Marşrut: {bus.get('firstPoint', '')} → {bus.get('lastPoint', '')}\n"
        f"Uzunluq: {bus.get('routLength', '?')} km\n"
        f"Müddət: {bus.get('durationMinuts', '?')} dəqiqə\n"
        f"Qiymət: {bus.get('tariffStr', '?')}\n"
        f"Ödəniş: {bus.get('paymentType', '?')}\n"
        f"Dayanacaqlar: {stop_names}"
    )

    reply = generate_response(message, context)
    return reply, buses


def _handle_stop_info(message: str, entities: dict) -> tuple[str, list]:
    stop_name = entities.get("stop_name", entities.get("destination", ""))
    if not stop_name:
        return generate_response(message, "Dayanacaq adı göstərilməyib."), []

    stops = matcher.match(stop_name, limit=1)
    if not stops:
        return f"'{stop_name}' adlı dayanacaq tapılmadı.", []

    detail = retriever.get_stop_detail(stops[0]["id"])
    if not detail:
        return f"'{stop_name}' haqqında məlumat tapılmadı.", []

    buses = detail.get("buses", [])
    bus_list = ", ".join(
        f"#{b['busNumber']} ({b['firstPoint']} → {b['lastPoint']})"
        for b in buses if b.get("busNumber")
    )

    context = (
        f"Dayanacaq: {detail['stopName']} (kod: {detail.get('stopCode', '')})\n"
        f"Koordinatlar: {detail.get('latitude')}, {detail.get('longitude')}\n"
        f"Transport qovşağı: {'Bəli' if detail.get('isTransportHub') else 'Xeyr'}\n"
        f"Bu dayanacaqdan keçən avtobuslar: {bus_list}"
    )

    reply = generate_response(message, context)
    return reply, []


def _handle_nearby_stops(session: Session, message: str) -> tuple[str, list]:
    if not session.has_location:
        return ask_for_location(), []

    stops = retriever.find_nearest_stops(session.latitude, session.longitude)
    if not stops:
        return "Yaxınlığınızda dayanacaq tapılmadı.", []

    stop_list = "\n".join(
        f"- {s['name']} ({s.get('distanceMeters', 0):.0f}m)"
        for s in stops[:5]
    )

    context = f"İstifadəçinin yaxınlığındakı dayanacaqlar:\n{stop_list}"
    reply = generate_response(message, context)
    return reply, stops


# ── Utility endpoints ───────────────────────────────

@router.get("/api/stops/nearby", response_model=NearbyStopsResponse)
def nearby_stops(lat: float, lng: float, radius: int = 500):
    stops = retriever.find_nearest_stops(lat, lng, radius=radius)
    return NearbyStopsResponse(stops=stops)


@router.get("/api/bus/{number}")
def get_bus(number: str):
    buses = retriever.find_bus_by_number(number)
    if not buses:
        raise HTTPException(status_code=404, detail="Bus not found")
    bus = buses[0]
    stops = retriever.get_bus_route_stops(bus["id"], direction=1)
    return {"bus": bus, "stops": stops}
