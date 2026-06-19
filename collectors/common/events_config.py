"""Loader for the Clair Obscur lifecycle event configuration.

Reads ``collectors/config/events.yaml`` and resolves an ``event_id`` to its
name, type, and date. The GCS writer uses the resolved id to choose the output
directory, and the collectors use it to fail loudly on an unknown event.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "events.yaml"


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
            ``collectors/config/events.yaml`` resolved relative to this package
            so it works inside the container.

    Returns:
        A mapping from ``event_id`` to its :class:`Event`.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the file is malformed or contains duplicate event ids.
    """
    config_path = path if path is not None else _CONFIG_PATH
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
