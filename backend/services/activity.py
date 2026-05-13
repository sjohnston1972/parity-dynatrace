"""In-memory pipeline activity bus for real-time model observability.

Tracks which Gemini model tier is currently working, what it's doing,
and recent completed activity. Consumed by the SSE endpoint and the
pipeline status API.
"""

import asyncio
import time
from dataclasses import dataclass, field, asdict
from enum import Enum

MAX_HISTORY = 100


class ActivityStatus(str, Enum):
    STARTED = "started"
    THINKING = "thinking"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ActivityEvent:
    id: str  # unique per event
    pipeline_run: str  # groups events for one pipeline invocation
    node: str  # detect, investigate, reason, etc.
    model: str  # gemini-2.5-flash, gemini-2.5-pro, gemini-2.5-flash-lite, pyats
    model_tier: str  # lite, flash, pro, engine
    device: str  # hostname being analysed
    status: str  # started, thinking, completed, failed
    detail: str = ""  # human-readable description of what the model is doing
    tokens: int = 0
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: int = 0

    def to_dict(self):
        return asdict(self)


# Gemini tier mapping. Order matters — "flash-lite" must match before "flash".
_MODEL_TIERS = [
    ("flash-lite", "lite"),
    ("pro", "pro"),
    ("flash", "flash"),
    ("pyats", "engine"),
]


def _resolve_tier(model: str) -> str:
    model_lower = (model or "").lower()
    for key, tier in _MODEL_TIERS:
        if key in model_lower:
            return tier
    return "unknown"


def _short_model(model: str) -> str:
    """Extract display name from full model ID."""
    model_lower = (model or "").lower()
    if "flash-lite" in model_lower:
        return "Gemini Flash-Lite"
    if "pro" in model_lower:
        return "Gemini Pro"
    if "flash" in model_lower:
        return "Gemini Flash"
    if "pyats" in model_lower:
        return "pyATS"
    return model or "?"


class ActivityBus:
    def __init__(self):
        self._active: dict[str, ActivityEvent] = {}  # id → event (currently running)
        self._history: list[ActivityEvent] = []
        self._subscribers: list[asyncio.Queue] = []
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"act-{self._counter}"

    def start(self, pipeline_run: str, node: str, model: str, device: str, detail: str = "") -> str:
        """Record that a model has started working. Returns event ID."""
        event_id = self._next_id()
        if not detail:
            short = _short_model(model)
            detail = f"{short} is analysing {device}"
        event = ActivityEvent(
            id=event_id,
            pipeline_run=pipeline_run,
            node=node,
            model=model,
            model_tier=_resolve_tier(model),
            device=device,
            status=ActivityStatus.STARTED,
            detail=detail,
            started_at=time.time(),
        )
        self._active[event_id] = event
        self._broadcast(event)
        return event_id

    def thinking(self, event_id: str, detail: str):
        """Update an active event with a thinking status."""
        event = self._active.get(event_id)
        if not event:
            return
        event.status = ActivityStatus.THINKING
        event.detail = detail
        self._broadcast(event)

    def complete(self, event_id: str, tokens: int = 0, detail: str = ""):
        """Mark a model invocation as completed."""
        event = self._active.pop(event_id, None)
        if not event:
            return
        event.status = ActivityStatus.COMPLETED
        event.completed_at = time.time()
        event.duration_ms = int((event.completed_at - event.started_at) * 1000)
        event.tokens = tokens
        if detail:
            event.detail = detail
        else:
            short = _short_model(event.model)
            event.detail = f"{short} finished — {tokens} tokens, {event.duration_ms}ms"
        self._history.append(event)
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]
        self._broadcast(event)

    def fail(self, event_id: str, error: str = ""):
        """Mark a model invocation as failed."""
        event = self._active.pop(event_id, None)
        if not event:
            return
        event.status = ActivityStatus.FAILED
        event.completed_at = time.time()
        event.duration_ms = int((event.completed_at - event.started_at) * 1000)
        event.detail = error or f"{_short_model(event.model)} failed"
        self._history.append(event)
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]
        self._broadcast(event)

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to activity events. Returns an asyncio Queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        """Remove a subscriber."""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _broadcast(self, event: ActivityEvent):
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    def get_active(self) -> list[dict]:
        return [e.to_dict() for e in self._active.values()]

    def get_history(self, limit: int = 50) -> list[dict]:
        return [e.to_dict() for e in reversed(self._history[-limit:])]

    def get_snapshot(self) -> dict:
        """Full state snapshot: active + recent history."""
        return {
            "active": self.get_active(),
            "history": self.get_history(),
        }


# Singleton
activity_bus = ActivityBus()
