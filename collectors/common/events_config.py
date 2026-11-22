"""Loader for a release's lifecycle event configuration.

Reads ``collectors/config/<release>/events.yaml`` (the release is chosen
by the ``RELEASE`` environment variable, see ``release_config``) and
resolves an ``event_id`` to its name, type, and date. The GCS writer uses
the resolved id to choose the output directory, and the collectors use it
to fail loudly on an unknown event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from collectors.common.release_config import release_config_dir

EVENTS_FILE = "events.yaml"
# Records whose date falls near no event land here. The raw archive layout
# allows it: {source}/{event_id_or_general}/...
GENERAL_EVENT_ID = "general"


@dataclass(frozen=True)
class Event:
    """A single lifecycle event of the studied release.

    Attributes:
        id: Stable identifier used as the ``EVENT_ID`` env var and output path
            segment (e.g. ``"launch"``).
        name: Human-readable event name.
        type: Event category (e.g. ``"reveal"``, ``"trailer"``, ``"launch"``).
        date_utc: Event date as an ISO 8601 date string (``YYYY-MM-DD``).
    """

    id: str
    name: str
    type: str
    date_utc: str


def load_events(path: Path | None = None) -> dict[str, Event]:
    """Load all configured events keyed by their id.

    Args:
        path: Optional override for the YAML config location. Defaults to
            the ``events.yaml`` of the release named by ``RELEASE``,
            resolved relative to this package so it works inside the
            container.

    Returns:
        A mapping from ``event_id`` to its :class:`Event`.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the file is malformed or contains duplicate event ids,
            or (without ``path``) if ``RELEASE`` is unset or unknown.
    """
    config_path = path if path is not None else release_config_dir() / EVENTS_FILE
    if not config_path.is_file():
        raise FileNotFoundError(f"Events config not found at {config_path}.")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    entries = raw.get("events")
    if not isinstance(entries, list):
        raise ValueError(f"{config_path} must contain a top-level 'events' list.")

    events: dict[str, Event] = {}
    for entry in entries:
        event = Event(
            id=str(entry["id"]),
            name=str(entry["name"]),
            type=str(entry["type"]),
            date_utc=str(entry["date_utc"]),
        )
        if event.id in events:
            raise ValueError(f"Duplicate event id in {config_path}: {event.id}.")
        events[event.id] = event

    return events


def resolve_event(event_id: str, path: Path | None = None) -> Event:
    """Resolve a single ``event_id`` to its :class:`Event`.

    Args:
        event_id: The id to look up.
        path: Optional override for the YAML config location.

    Returns:
        The matching :class:`Event`.

    Raises:
        KeyError: If ``event_id`` is not present in the config. Collectors must
            treat this as a hard failure rather than writing to an unknown path.
    """
    events = load_events(path)
    try:
        return events[event_id]
    except KeyError as exc:
        known = ", ".join(sorted(events)) or "<none>"
        raise KeyError(f"Unknown event_id '{event_id}'. Known ids: {known}.") from exc


def event_tag_for(
    created: datetime,
    events: dict[str, Event],
    window_days: float,
) -> str:
    """Return the lifecycle event a record belongs to, by its own date.

    Used by collectors that read a long span in one pass (Steam's
    newest-first walk, Bluesky's sliced search) and so cannot tag a whole
    run with one ``EVENT_ID``.

    Args:
        created: The record's creation time (UTC).
        events: Configured events, keyed by id.
        window_days: Half-width of the window around each event date.

    Returns:
        The id of the nearest event within the window, or
        :data:`GENERAL_EVENT_ID` when the record falls near none. Ties go
        to the earlier event date, then to the smaller id, so tagging is
        deterministic across runs.
    """
    best: tuple[float, str, str] | None = None
    for event in events.values():
        event_day = datetime.fromisoformat(f"{event.date_utc}T00:00:00+00:00")
        distance_days = abs((created - event_day).total_seconds()) / 86400.0
        if distance_days > window_days:
            continue
        candidate = (distance_days, event.date_utc, event.id)
        if best is None or candidate < best:
            best = candidate
    return best[2] if best is not None else GENERAL_EVENT_ID
