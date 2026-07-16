import json
from datetime import UTC, datetime

from publisher.replay import (
    build_message,
    build_replay_query,
    compute_sleep_seconds,
)


def _ts(second: int) -> datetime:
    return datetime(2025, 4, 24, 12, 0, second, tzinfo=UTC)


class TestComputeSleepSeconds:
    def test_first_record_sleeps_zero(self):
        assert compute_sleep_seconds(None, _ts(30), speedup=60, max_sleep=5) == 0.0

    def test_gap_divided_by_speedup(self):
        assert compute_sleep_seconds(_ts(0), _ts(30), speedup=60, max_sleep=5) == 0.5

    def test_speedup_one_is_passthrough(self):
        assert compute_sleep_seconds(_ts(0), _ts(3), speedup=1, max_sleep=10) == 3.0

    def test_huge_gap_clamps_to_max_sleep(self):
        prev = datetime(2024, 6, 9, tzinfo=UTC)
        curr = datetime(2025, 4, 24, tzinfo=UTC)  # months later
        assert compute_sleep_seconds(prev, curr, speedup=86400, max_sleep=5) == 5.0

    def test_negative_gap_sleeps_zero(self):
        assert compute_sleep_seconds(_ts(30), _ts(0), speedup=60, max_sleep=5) == 0.0

    def test_zero_gap_sleeps_zero(self):
        assert compute_sleep_seconds(_ts(10), _ts(10), speedup=60, max_sleep=5) == 0.0


class TestBuildReplayQuery:
    def test_no_filters_has_no_parameters(self):
        sql, params = build_replay_query("proj", "ds", "raw_staging")
        assert params == []
        assert "`proj.ds.raw_staging`" in sql
        assert sql.endswith("ORDER BY created_utc, id")

    def test_event_filter_adds_parameter(self):
        sql, params = build_replay_query("proj", "ds", "raw_staging", event_id="launch")
        assert "event_tag = @event_id" in sql
        assert len(params) == 1
        assert params[0].name == "event_id"
        assert params[0].value == "launch"
        # Values must never be interpolated into the SQL text.
        assert "launch" not in sql

    def test_window_filters_add_parameters(self):
        window_from = datetime(2025, 4, 24, tzinfo=UTC)
        window_to = datetime(2025, 5, 1, tzinfo=UTC)
        sql, params = build_replay_query(
            "proj",
            "ds",
            "raw_staging",
            window_from=window_from,
            window_to=window_to,
        )
        assert "created_utc >= @window_from" in sql
        assert "created_utc < @window_to" in sql
        assert [p.name for p in params] == ["window_from", "window_to"]
        assert "2025" not in sql

    def test_all_filters_combined(self):
        sql, params = build_replay_query(
            "proj",
            "ds",
            "raw_staging",
            event_id="launch",
            window_from=datetime(2025, 4, 24, tzinfo=UTC),
            window_to=datetime(2025, 5, 1, tzinfo=UTC),
        )
        assert [p.name for p in params] == ["event_id", "window_from", "window_to"]
        assert sql.endswith("ORDER BY created_utc, id")


class TestBuildMessage:
    def _record(self) -> dict[str, object]:
        return {
            "id": "youtube:Ugxabc123",
            "source": "youtube",
            "parent_id": None,
            "created_utc": datetime(2025, 4, 24, 12, 34, 56, tzinfo=UTC),
            "collected_at": datetime(2026, 7, 5, 9, 0, 0, tzinfo=UTC),
            "author_hash": "a" * 16,
            "text": "Peak fiction, honestly.",
            "language": "en",
            "score": 42,
            "context_id": "2VaLOc1FpSo",
            "event_tag": "launch",
        }

    def test_payload_round_trips_with_iso_timestamps(self):
        data, _ = build_message(self._record(), replayed_at="2026-07-16T10:00:00Z")
        payload = json.loads(data.decode("utf-8"))
        assert payload["id"] == "youtube:Ugxabc123"
        assert payload["created_utc"] == "2025-04-24T12:34:56Z"
        assert payload["collected_at"] == "2026-07-05T09:00:00Z"
        assert payload["parent_id"] is None
        assert payload["score"] == 42
        assert set(payload) == set(self._record())

    def test_attribute_set_is_exact(self):
        _, attributes = build_message(
            self._record(), replayed_at="2026-07-16T10:00:00Z"
        )
        assert attributes == {
            "source": "youtube",
            "event_tag": "launch",
            "created_utc": "2025-04-24T12:34:56Z",
            "replayed_at": "2026-07-16T10:00:00Z",
        }

    def test_missing_optional_attributes_become_empty_strings(self):
        record = self._record()
        record["event_tag"] = None
        _, attributes = build_message(record, replayed_at="2026-07-16T10:00:00Z")
        assert attributes["event_tag"] == ""
