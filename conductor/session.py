"""Session management — tracks user location and conversation history."""

import uuid
from dataclasses import dataclass, field


@dataclass
class Session:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    latitude: float | None = None
    longitude: float | None = None
    nearest_stops: list[dict] = field(default_factory=list)
    location_source: str = "unknown"  # "geolocation" | "manual" | "unknown"
    conversation_history: list[dict] = field(default_factory=list)
    pending_destination: str | None = None  # saved when route_find needs location
    language: str = "az"

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def add_user_message(self, text: str):
        self.conversation_history.append(
            {"role": "user", "parts": [{"text": text}]}
        )

    def add_model_message(self, text: str):
        self.conversation_history.append(
            {"role": "model", "parts": [{"text": text}]}
        )


class SessionStore:
    """In-memory session store. Replace with Redis/SQLite for production."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        session = Session()
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str):
        self._sessions.pop(session_id, None)
