"""Tests for the Steam reviews collector.

Three things matter beyond "it parses JSON": the window cutoff must stop
a run rather than walk the whole review history, pagination must not loop
forever on a stuck cursor, and nothing about the author except the salted
hash of their steamid may reach a record.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from collectors.common.events_config import Event
from collectors.steam.main import (
    GENERAL_EVENT_ID,
    RunConfig,
    collect,
    event_tag_for,
    review_record,
)


def _config(**overrides) -> RunConfig:
    base = dict(
        target_bucket="bucket",
        salt="pepper",
        event_id="launch",
        window_from=datetime(2025, 4, 24, tzinfo=UTC),
        window_to=datetime(2025, 5, 1, tzinfo=UTC),
        appid="1903340",
        page_sleep_seconds=0.0,
        max_pages=50,
        event_window_days=3.0,
    )
    base.update(overrides)
    return RunConfig(**base)


def _review(rid: str, created: datetime, **overrides) -> dict:
    review = {
        "recommendationid": rid,
        "author": {
            "steamid": "76561198000000001",
            "personaname": "SomePlayer",
            "profile_url": "https://steamcommunity.com/id/someplayer/",
        },
        "review": "Fantastic turn-based combat.",
        "language": "english",
        "timestamp_created": int(created.timestamp()),
        "voted_up": True,
        "votes_up": 7,
    }
    review.update(overrides)
    return review


class _FakeSession:
    """Session double returning canned pages, keyed by cursor."""

    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.calls = 0
        self.headers: dict[str, str] = {}

    def get(self, url, params=None, timeout=None):  # noqa: ANN001, ANN201
        page = self.pages[min(self.calls, len(self.pages) - 1)]
        self.calls += 1
        return _FakeResponse(page)

    def close(self) -> None:
        pass


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def written(monkeypatch):
    """Capture what the collector would write to GCS."""
    batches: list[list[dict]] = []

    def fake_write_batch(records, source, event_id, bucket):  # noqa: ANN001, ANN202
        batches.append(list(records))
        return f"gs://{bucket}/{source}/{event_id}/batch.jsonl.gz"

    monkeypatch.setattr("collectors.steam.main.write_batch", fake_write_batch)
    return batches


def test_record_keeps_only_the_hashed_author(written):
    record = review_record(_review("r1", datetime(2025, 4, 25, tzinfo=UTC)), _config())

    assert record["id"] == "steam:r1"
    assert record["source"] == "steam"
    assert record["parent_id"] is None
    assert record["context_id"] == "1903340"
    assert record["score"] == 7
    assert record["voted_up"] is True
    assert len(record["author_hash"]) == 16
    serialised = str(record)
    assert "SomePlayer" not in serialised
    assert "steamcommunity.com" not in serialised
    assert "76561198000000001" not in serialised


def test_thumbs_down_is_preserved_as_false(written):
    record = review_record(
        _review("r2", datetime(2025, 4, 25, tzinfo=UTC), voted_up=False), _config()
    )

    assert record["voted_up"] is False


def test_reviews_outside_the_window_are_skipped(written):
    session = _FakeSession(
        [
            {
                "success": 1,
                "reviews": [
                    # Newer than window_to: skipped, but reading continues.
                    _review("too-new", datetime(2025, 6, 1, tzinfo=UTC)),
                    _review("inside", datetime(2025, 4, 26, tzinfo=UTC)),
                    # Older than window_from: ends the run.
                    _review("too-old", datetime(2025, 4, 1, tzinfo=UTC)),
                    _review("never-read", datetime(2025, 3, 1, tzinfo=UTC)),
                ],
                "cursor": "page2",
            }
        ]
    )

    total = collect(_config(), session=session)

    assert total == 1
    assert [r["id"] for r in written[0]] == ["steam:inside"]
    # Stopped on the first page: descending order means nothing newer follows.
    assert session.calls == 1


def test_pagination_stops_when_the_cursor_repeats(written):
    page = {
        "success": 1,
        "reviews": [_review("r1", datetime(2025, 4, 26, tzinfo=UTC))],
        "cursor": "same-cursor",
    }
    session = _FakeSession([page])

    collect(_config(), session=session)

    # The second page carries the same cursor, so the run stops instead of
    # fetching that page until the cap.
    assert session.calls == 2


def test_empty_page_ends_the_run(written):
    session = _FakeSession([{"success": 1, "reviews": [], "cursor": "x"}])

    total = collect(_config(), session=session)

    assert total == 0
    assert written == []


def test_endpoint_failure_is_not_silently_ignored(written):
    session = _FakeSession([{"success": 0, "reviews": []}])

    with pytest.raises(RuntimeError, match="reported failure"):
        collect(_config(), session=session)


# --- auto tagging -----------------------------------------------------------

_EVENTS = {
    "launch": Event("launch", "Worldwide launch", "launch", "2025-04-24"),
    "ai_textures_controversy": Event(
        "ai_textures_controversy", "AI textures", "controversy", "2025-04-26"
    ),
    "tga_2025_sweep": Event("tga_2025_sweep", "TGA sweep", "award", "2025-12-11"),
}


@pytest.mark.parametrize(
    "created, expected",
    [
        (datetime(2025, 4, 24, 12, tzinfo=UTC), "launch"),
        # Nearer to the controversy than to launch.
        (datetime(2025, 4, 26, 6, tzinfo=UTC), "ai_textures_controversy"),
        (datetime(2025, 12, 11, tzinfo=UTC), "tga_2025_sweep"),
        # Three weeks after launch: inside no window.
        (datetime(2025, 5, 15, tzinfo=UTC), GENERAL_EVENT_ID),
    ],
)
def test_auto_tag_picks_the_nearest_event(created, expected):
    assert event_tag_for(created, _EVENTS, window_days=3.0) == expected


def test_auto_tag_is_deterministic_on_ties():
    # Exactly between launch (04-24) and the controversy (04-26): the tie
    # goes to the earlier event date, every run.
    midpoint = datetime(2025, 4, 25, tzinfo=UTC)

    first = event_tag_for(midpoint, _EVENTS, window_days=3.0)
    second = event_tag_for(midpoint, dict(reversed(list(_EVENTS.items()))), 3.0)

    assert first == second == "launch"


def test_auto_tagging_writes_one_batch_per_event(written, monkeypatch):
    monkeypatch.setattr("collectors.steam.main.load_events", lambda: _EVENTS)
    session = _FakeSession(
        [
            {
                "success": 1,
                "reviews": [
                    _review("tga", datetime(2025, 12, 11, tzinfo=UTC)),
                    _review("quiet", datetime(2025, 5, 15, tzinfo=UTC)),
                    _review("launch-day", datetime(2025, 4, 24, 9, tzinfo=UTC)),
                ],
                "cursor": "end",
            },
            # The real endpoint ends the walk with an empty page.
            {"success": 1, "reviews": [], "cursor": "end"},
        ]
    )
    config = _config(
        event_id="auto",
        window_from=datetime(2025, 4, 1, tzinfo=UTC),
        window_to=datetime(2026, 1, 1, tzinfo=UTC),
    )

    total = collect(config, session=session)

    assert total == 3
    by_tag = {record["event_tag"] for batch in written for record in batch}
    assert by_tag == {"tga_2025_sweep", GENERAL_EVENT_ID, "launch"}
    # One object per tag, not one mixed object.
    assert len(written) == 3
