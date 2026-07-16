import pytest

from publisher.config import DEFAULT_PUBSUB_ENDPOINT, load_config

REQUIRED_ENV = {
    "PROJECT_ID": "proj",
    "BQ_DATASET": "co_analytics_dev",
    "BQ_LANDING_TABLE": "raw_landing",
    "BQ_STAGING_TABLE": "raw_staging",
    "RAW_ARCHIVE_BUCKET": "co-raw-archive-dev",
    "PUBSUB_TOPIC": "co-events-topic-dev",
}


@pytest.fixture()
def base_env(monkeypatch):
    for name, value in REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    for name in (
        "SPEEDUP",
        "MAX_SLEEP_SECONDS",
        "RUN_LOAD",
        "EVENT_ID",
        "WINDOW_FROM",
        "WINDOW_TO",
        "PUBSUB_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class TestRequiredEnv:
    @pytest.mark.parametrize("missing", sorted(REQUIRED_ENV))
    def test_missing_required_variable_fails_loudly(self, base_env, missing):
        base_env.delenv(missing)
        with pytest.raises(ValueError, match=missing):
            load_config()


class TestDefaults:
    def test_defaults_match_deployed_job(self, base_env):
        config = load_config()
        assert config.speedup == 86400.0
        assert config.max_sleep_seconds == 5.0
        assert config.run_load == "false"
        assert config.event_id is None
        assert config.window_from is None
        assert config.window_to is None
        assert config.pubsub_endpoint == DEFAULT_PUBSUB_ENDPOINT


class TestValidation:
    def test_zero_speedup_rejected(self, base_env):
        base_env.setenv("SPEEDUP", "0")
        with pytest.raises(ValueError, match="SPEEDUP"):
            load_config()

    def test_negative_speedup_rejected(self, base_env):
        base_env.setenv("SPEEDUP", "-1")
        with pytest.raises(ValueError, match="SPEEDUP"):
            load_config()

    def test_negative_max_sleep_rejected(self, base_env):
        base_env.setenv("MAX_SLEEP_SECONDS", "-0.1")
        with pytest.raises(ValueError, match="MAX_SLEEP_SECONDS"):
            load_config()

    def test_junk_run_load_rejected(self, base_env):
        base_env.setenv("RUN_LOAD", "maybe")
        with pytest.raises(ValueError, match="RUN_LOAD"):
            load_config()

    def test_run_load_case_insensitive(self, base_env):
        base_env.setenv("RUN_LOAD", "ONLY")
        assert load_config().run_load == "only"

    def test_inverted_window_rejected(self, base_env):
        base_env.setenv("WINDOW_FROM", "2025-05-01T00:00:00Z")
        base_env.setenv("WINDOW_TO", "2025-04-24T00:00:00Z")
        with pytest.raises(ValueError, match="WINDOW_FROM"):
            load_config()


class TestEventId:
    def test_known_event_id_resolves(self, base_env):
        base_env.setenv("EVENT_ID", "launch")
        assert load_config().event_id == "launch"

    def test_unknown_event_id_fails_loudly(self, base_env):
        base_env.setenv("EVENT_ID", "definitely-not-an-event")
        with pytest.raises(KeyError, match="definitely-not-an-event"):
            load_config()


class TestWindows:
    def test_window_parsed_as_utc(self, base_env):
        base_env.setenv("WINDOW_FROM", "2025-04-24T00:00:00Z")
        base_env.setenv("WINDOW_TO", "2025-05-01T00:00:00Z")
        config = load_config()
        assert config.window_from is not None
        assert config.window_to is not None
        assert config.window_from.isoformat() == "2025-04-24T00:00:00+00:00"
        assert config.window_from < config.window_to
