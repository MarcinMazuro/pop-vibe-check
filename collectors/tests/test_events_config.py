"""Tests for the event-config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from collectors.common.events_config import load_events, resolve_event
from collectors.common.release_config import known_releases, release_config_dir

_VALID_YAML = """
events:
  - id: launch
    name: Worldwide launch
    type: launch
    date_utc: 2025-04-24
  - id: reveal
    name: Reveal
    type: reveal
    date_utc: 2024-06-09
"""


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "events.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_events_returns_mapping(tmp_path: Path):
    events = load_events(_write(tmp_path, _VALID_YAML))
    assert set(events) == {"launch", "reveal"}
    assert events["launch"].name == "Worldwide launch"
    assert events["launch"].type == "launch"
    assert events["launch"].date_utc == "2025-04-24"


def test_resolve_known_event(tmp_path: Path):
    event = resolve_event("launch", _write(tmp_path, _VALID_YAML))
    assert event.id == "launch"


def test_resolve_unknown_event_raises(tmp_path: Path):
    with pytest.raises(KeyError):
        resolve_event("nope", _write(tmp_path, _VALID_YAML))


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_events(tmp_path / "does_not_exist.yaml")


def test_duplicate_ids_raise(tmp_path: Path):
    content = """
events:
  - id: launch
    name: One
    type: launch
    date_utc: 2025-04-24
  - id: launch
    name: Two
    type: launch
    date_utc: 2025-04-25
"""
    with pytest.raises(ValueError):
        load_events(_write(tmp_path, content))


def test_repository_events_config_is_valid_and_has_twelve_entries(monkeypatch):
    monkeypatch.setenv("RELEASE", "clair_obscur")
    events = load_events()
    assert len(events) == 12
    assert "launch" in events


@pytest.mark.parametrize("release", known_releases())
def test_every_release_has_a_valid_events_config_with_a_launch(release):
    events = load_events(release_config_dir(release) / "events.yaml")
    assert "launch" in events


def test_load_events_without_release_fails_loudly(monkeypatch):
    monkeypatch.delenv("RELEASE", raising=False)
    with pytest.raises(ValueError, match="RELEASE"):
        load_events()
