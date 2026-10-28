"""CPU-safe tests for nlp.tracking: the IAP token and the migration helpers.

MLflow itself is Workbench-only and not installed here, so the tests cover
the parts that do not import it.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from nlp.tracking import mlflow_utils
from nlp.tracking.migrate import chunked, main, split_gs_uri, terminal_status


class _FakeTimer:
    """Records what a threading.Timer would have scheduled."""

    started: list[_FakeTimer] = []

    def __init__(self, interval: float, function: Any, args: tuple[Any, ...]):
        self.interval = interval
        self.function = function
        self.args = args
        self.daemon = False

    def start(self) -> None:
        _FakeTimer.started.append(self)


def test_use_iap_token_sets_env_and_schedules_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import google.oauth2.id_token

    audiences: list[str] = []

    def fake_fetch(_request: Any, audience: str) -> str:
        audiences.append(audience)
        return f"token-{len(audiences)}"

    monkeypatch.setattr(google.oauth2.id_token, "fetch_id_token", fake_fetch)
    monkeypatch.setattr(mlflow_utils.threading, "Timer", _FakeTimer)
    monkeypatch.delenv("MLFLOW_TRACKING_TOKEN", raising=False)
    _FakeTimer.started.clear()

    mlflow_utils.use_iap_token("client-id.apps.googleusercontent.com")

    assert os.environ["MLFLOW_TRACKING_TOKEN"] == "token-1"
    assert audiences == ["client-id.apps.googleusercontent.com"]
    (timer,) = _FakeTimer.started
    assert timer.daemon
    assert timer.interval == mlflow_utils.IAP_TOKEN_REFRESH_SECONDS
    assert timer.interval < 3600  # before the hour-long token expires

    # The refresh is the same call: a new token replaces the old one.
    timer.function(*timer.args)
    assert os.environ["MLFLOW_TRACKING_TOKEN"] == "token-2"


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (
            "gs://bucket/nlp/mlruns/abc/artifacts",
            ("bucket", "nlp/mlruns/abc/artifacts"),
        ),
        ("gs://bucket/nlp/mlruns/", ("bucket", "nlp/mlruns")),
        ("gs://bucket", ("bucket", "")),
    ],
)
def test_split_gs_uri(uri: str, expected: tuple[str, str]) -> None:
    assert split_gs_uri(uri) == expected


@pytest.mark.parametrize("uri", ["file:///home/jupyter/mlruns", "gs://", "/tmp/x"])
def test_split_gs_uri_rejects_non_gcs(uri: str) -> None:
    with pytest.raises(ValueError):
        split_gs_uri(uri)


def test_chunked_keeps_order_and_bounds() -> None:
    assert list(chunked(list(range(5)), 2)) == [[0, 1], [2, 3], [4]]
    assert list(chunked([], 100)) == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("FINISHED", ("FINISHED", False)),
        ("FAILED", ("FAILED", False)),
        ("KILLED", ("KILLED", False)),
        ("RUNNING", ("KILLED", True)),
        ("SCHEDULED", ("KILLED", True)),
    ],
)
def test_terminal_status(status: str, expected: tuple[str, bool]) -> None:
    assert terminal_status(status) == expected


def test_main_requires_server_uri_and_audience(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "gs://bucket/nlp/mlruns")
    monkeypatch.setenv(mlflow_utils.IAP_AUDIENCE_ENV, "client-id")
    assert main(["--source", str(tmp_path)]) == 2

    monkeypatch.setenv("MLFLOW_TRACKING_URI", "https://co-mlflow-dev-x.a.run.app")
    monkeypatch.delenv(mlflow_utils.IAP_AUDIENCE_ENV)
    assert main(["--source", str(tmp_path)]) == 2

    monkeypatch.setenv(mlflow_utils.IAP_AUDIENCE_ENV, "client-id")
    assert main(["--source", str(tmp_path / "missing")]) == 2
