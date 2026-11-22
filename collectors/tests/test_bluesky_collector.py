"""Tests for the Bluesky collector."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from collectors.bluesky import main as bsky
from collectors.bluesky.main import (
    BlueskyClient,
    BlueskyError,
    RunConfig,
    collect,
    parse_queries,
    post_created,
    post_record,
    pseudonymous_post_id,
    resolve_window,
    window_slices,
)
from collectors.common.author_hash import hash_author
from collectors.common.events_config import GENERAL_EVENT_ID, Event

SALT = "test-salt"
DID = "did:plc:abcdefghijklmnopqrstuvwx"
OTHER_DID = "did:plc:zyxwvutsrqponmlkjihgfedc"


@pytest.fixture(autouse=True)
def _release(monkeypatch):
    monkeypatch.setenv("RELEASE", "gta6")


def _config(**overrides) -> RunConfig:
    base = dict(
        target_bucket="gta6-raw-archive-dev",
        salt=SALT,
        event_id="launch",
        window_from=datetime(2026, 11, 19, 0, tzinfo=UTC),
        window_to=datetime(2026, 11, 19, 12, tzinfo=UTC),
        handle="collector.bsky.social",
        app_password="xxxx-xxxx-xxxx-xxxx",
        pds_url="https://bsky.social",
        queries=('"GTA 6"',),
        slice_minutes=360.0,
        max_pages_per_slice=100,
        page_sleep_seconds=0.0,
        event_window_days=3.0,
    )
    base.update(overrides)
    return RunConfig(**base)


def _post(
    rkey: str,
    created: datetime,
    text: str = "GTA 6 is incredible",
    did: str = DID,
    parent: str | None = None,
    langs: list[str] | None = None,
    likes: int = 3,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": created.isoformat().replace("+00:00", "Z"),
    }
    if langs is not None:
        record["langs"] = langs
    if parent:
        record["reply"] = {"parent": {"uri": parent}, "root": {"uri": parent}}
    return {
        "uri": f"at://{did}/app.bsky.feed.post/{rkey}",
        "cid": "bafy" + rkey,
        "author": {
            "did": did,
            "handle": "real-person.bsky.social",
            "displayName": "Real Person",
            "avatar": "https://cdn.bsky.app/avatar.jpg",
        },
        "record": record,
        "likeCount": likes,
        "indexedAt": created.isoformat().replace("+00:00", "Z"),
    }


# ---------------------------------------------------------------- config


def test_parse_queries_splits_on_semicolons_and_dedupes():
    assert parse_queries(' "GTA 6" ; GTA6;; "GTA 6" ;"GTA VI"') == (
        '"GTA 6"',
        "GTA6",
        '"GTA VI"',
    )


def test_parse_queries_rejects_empty():
    with pytest.raises(ValueError):
        parse_queries(" ; ")


@pytest.fixture()
def window_env(monkeypatch):
    for name in ("WINDOW_FROM", "WINDOW_TO", "WINDOW_LOOKBACK_MINUTES"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_explicit_window(window_env):
    window_env.setenv("WINDOW_FROM", "2026-11-19T00:00:00Z")
    window_env.setenv("WINDOW_TO", "2026-11-20T00:00:00Z")
    assert resolve_window() == (
        datetime(2026, 11, 19, tzinfo=UTC),
        datetime(2026, 11, 20, tzinfo=UTC),
    )


def test_lookback_window_ends_now(window_env):
    window_env.setenv("WINDOW_LOOKBACK_MINUTES", "30")
    now = datetime(2026, 11, 22, 12, 0, 30, 123456, tzinfo=UTC)
    start, end = resolve_window(now)
    assert end == datetime(2026, 11, 22, 12, 0, 30, tzinfo=UTC)
    assert end - start == timedelta(minutes=30)


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"WINDOW_FROM": "2026-11-19T00:00:00Z"},
        {"WINDOW_LOOKBACK_MINUTES": "30", "WINDOW_FROM": "2026-11-19T00:00:00Z"},
        {"WINDOW_LOOKBACK_MINUTES": "0"},
        {"WINDOW_FROM": "2026-11-20T00:00:00Z", "WINDOW_TO": "2026-11-19T00:00:00Z"},
    ],
)
def test_bad_windows_fail_loudly(window_env, env):
    for name, value in env.items():
        window_env.setenv(name, value)
    with pytest.raises(ValueError):
        resolve_window()


def test_slices_cover_the_window_once_newest_first():
    start = datetime(2026, 11, 19, 0, tzinfo=UTC)
    end = datetime(2026, 11, 19, 13, tzinfo=UTC)
    slices = window_slices(start, end, 360)
    assert slices[0] == (datetime(2026, 11, 19, 7, tzinfo=UTC), end)
    assert slices[-1] == (start, datetime(2026, 11, 19, 1, tzinfo=UTC))
    for (since, _), (_, until) in zip(slices, slices[1:], strict=False):
        assert since == until


# ---------------------------------------------------------------- records


def test_post_id_hides_the_author_and_is_stable():
    uri = f"at://{DID}/app.bsky.feed.post/3kabc"
    first = pseudonymous_post_id(uri, SALT)
    assert first == pseudonymous_post_id(uri, SALT)
    assert first.startswith("bluesky:") and len(first) == len("bluesky:") + 32
    assert DID not in first and "3kabc" not in first
    # The id is exposed by the reporting layer, so it must not let anyone
    # group posts by author.
    assert hash_author(DID, SALT) not in first
    same_author_other_post = f"at://{DID}/app.bsky.feed.post/3kxyz"
    assert first != pseudonymous_post_id(same_author_other_post, SALT)
    assert first != pseudonymous_post_id(uri, "another-salt")


def test_post_id_rejects_non_at_uris():
    with pytest.raises(ValueError):
        pseudonymous_post_id("https://bsky.app/profile/x/post/3k", SALT)


def test_created_is_the_earlier_of_created_at_and_indexed_at():
    indexed = datetime(2026, 11, 19, 10, tzinfo=UTC)
    post = _post("3k1", indexed)
    post["record"]["createdAt"] = "2030-01-01T00:00:00Z"  # future-dated client
    assert post_created(post) == indexed


def test_record_never_carries_author_identity():
    created = datetime(2026, 11, 19, 10, tzinfo=UTC)
    parent = f"at://{OTHER_DID}/app.bsky.feed.post/3kparent"
    post = _post("3kchild", created, parent=parent, langs=["pl"])
    record = post_record(post, _config(), "launch", '"GTA 6"')

    serialised = json.dumps(record)
    for leaked in (DID, OTHER_DID, "real-person", "Real Person", "avatar"):
        assert leaked not in serialised

    assert record["parent_id"] == pseudonymous_post_id(parent, SALT)
    assert record["language"] == "pl"
    assert record["score"] == 3
    assert record["context_id"] == '"GTA 6"'
    assert record["voted_up"] is None
    assert record["created_utc"] == "2026-11-19T10:00:00Z"


def test_reply_id_matches_its_parents_own_id():
    created = datetime(2026, 11, 19, 10, tzinfo=UTC)
    parent_post = _post("3kparent", created, did=OTHER_DID)
    child = _post(
        "3kchild", created, parent=f"at://{OTHER_DID}/app.bsky.feed.post/3kparent"
    )
    parent_record = post_record(parent_post, _config(), "launch", "q")
    child_record = post_record(child, _config(), "launch", "q")
    assert child_record["parent_id"] == parent_record["id"]


# ---------------------------------------------------------------- collect


class FakeClient:
    """Serves canned search pages keyed by (query, since)."""

    def __init__(self, pages: dict[tuple[str, str], list[dict[str, Any]]]):
        """Hold the canned pages."""
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def get(self, nsid: str, params: dict[str, Any]) -> dict[str, Any]:
        assert nsid == "app.bsky.feed.searchPosts"
        self.calls.append(dict(params))
        stream = self.pages.get((params["q"], params["since"]), [])
        index = int(params.get("cursor") or 0)
        if index >= len(stream):
            return {"posts": []}
        page = dict(stream[index])
        if index + 1 < len(stream):
            page["cursor"] = str(index + 1)
        return page


@pytest.fixture()
def written(monkeypatch):
    batches: list[tuple[str, list[dict[str, Any]]]] = []

    def fake_write(records, source, event_id, bucket=None):
        assert source == "bluesky"
        batches.append((event_id, list(records)))
        return f"gs://{bucket}/{source}/{event_id}/x.jsonl.gz"

    monkeypatch.setattr(bsky, "write_batch", fake_write)
    return batches


def _all(batches):
    return [r for _, records in batches for r in records]


def test_collect_dedupes_across_queries_and_skips_textless(written):
    t = datetime(2026, 11, 19, 8, tzinfo=UTC)
    shared = _post("3kshared", t)
    pages = {
        ('"GTA 6"', "2026-11-19T06:00:00Z"): [
            {"posts": [shared, _post("3kimg", t, text="  ")]}
        ],
        ("GTA6", "2026-11-19T06:00:00Z"): [{"posts": [shared, _post("3kb", t)]}],
    }
    total = collect(_config(queries=('"GTA 6"', "GTA6")), client=FakeClient(pages))
    ids = [r["id"] for r in _all(written)]
    assert total == 2
    assert len(ids) == len(set(ids)) == 2


def test_collect_drops_posts_outside_their_slice(written):
    edge = datetime(2026, 11, 19, 6, tzinfo=UTC)  # belongs to the later slice
    pages = {
        ('"GTA 6"', "2026-11-19T06:00:00Z"): [{"posts": [_post("3knew", edge)]}],
        # The API returning the edge post again for the older slice must not
        # produce a second copy.
        ('"GTA 6"', "2026-11-19T00:00:00Z"): [{"posts": [_post("3knew", edge)]}],
    }
    collect(_config(), client=FakeClient(pages))
    assert len(_all(written)) == 1


def test_collect_follows_cursors_and_respects_the_page_cap(written, caplog):
    t = datetime(2026, 11, 19, 8, tzinfo=UTC)
    stream = [{"posts": [_post(f"3k{i}", t)]} for i in range(5)]
    pages = {('"GTA 6"', "2026-11-19T06:00:00Z"): stream}
    client = FakeClient(pages)
    collect(_config(max_pages_per_slice=3), client=client)
    assert len(_all(written)) == 3
    assert "page cap" in caplog.text


def test_collect_auto_tags_by_post_date(written, monkeypatch):
    events = {
        "launch": Event("launch", "Launch", "launch", "2026-11-19"),
        "trailer_2": Event("trailer_2", "Trailer 2", "trailer", "2025-05-06"),
    }
    monkeypatch.setattr(bsky, "load_events", lambda: events)
    config = _config(
        event_id="auto",
        window_from=datetime(2026, 11, 1, tzinfo=UTC),
        window_to=datetime(2026, 11, 20, tzinfo=UTC),
        slice_minutes=60 * 24 * 30,
    )
    pages = {
        ('"GTA 6"', "2026-11-01T00:00:00Z"): [
            {
                "posts": [
                    _post("3knear", datetime(2026, 11, 19, 9, tzinfo=UTC)),
                    _post("3kfar", datetime(2026, 11, 2, 9, tzinfo=UTC)),
                ]
            }
        ]
    }
    collect(config, client=FakeClient(pages))
    near = pseudonymous_post_id(f"at://{DID}/app.bsky.feed.post/3knear", SALT)
    far = pseudonymous_post_id(f"at://{DID}/app.bsky.feed.post/3kfar", SALT)
    tags = {r["id"]: tag for tag, rs in written for r in rs}
    assert tags == {near: "launch", far: GENERAL_EVENT_ID}


def test_collect_rejects_an_unknown_event(written):
    with pytest.raises(KeyError):
        collect(_config(event_id="nope"), client=FakeClient({}))


# ---------------------------------------------------------------- client


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status: int, body: dict[str, Any] | None = None):
        """Hold status and body."""
        self.status_code = status
        self._body = body or {}
        self.text = json.dumps(self._body)
        self.headers: dict[str, str] = {}

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(response=self)  # type: ignore[arg-type]


class FakeSession:
    """Replays queued responses and records requests."""

    def __init__(self, responses: list[FakeResponse]):
        """Queue the responses."""
        self.responses = responses
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.headers: dict[str, str] = {}

    def _next(self, method: str, url: str, **kwargs) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        return self._next("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self._next("GET", url, **kwargs)

    def close(self):
        pass


_SESSION_BODY = {
    "accessJwt": "access-1",
    "refreshJwt": "refresh-1",
    "did": DID,
    "didDoc": {
        "service": [
            {
                "id": "#atproto_pds",
                "type": "AtprotoPersonalDataServer",
                "serviceEndpoint": "https://morel.us-east.host.bsky.network",
            }
        ]
    },
}


def test_login_uses_the_accounts_own_pds_afterwards():
    session = FakeSession(
        [FakeResponse(200, _SESSION_BODY), FakeResponse(200, {"posts": []})]
    )
    client = BlueskyClient("https://bsky.social", "me.bsky.social", "pw", session)
    client.login()
    client.get("app.bsky.feed.searchPosts", {"q": "x"})

    login_url = session.requests[0][1]
    search_method, search_url, kwargs = session.requests[1]
    assert login_url == "https://bsky.social/xrpc/com.atproto.server.createSession"
    assert search_url.startswith("https://morel.us-east.host.bsky.network/xrpc/")
    assert kwargs["headers"]["Authorization"] == "Bearer access-1"
    assert kwargs["headers"]["atproto-proxy"] == "did:web:api.bsky.app#bsky_appview"


def test_rejected_credentials_fail_without_retrying():
    session = FakeSession([FakeResponse(401, {"error": "AuthenticationRequired"})] * 3)
    client = BlueskyClient("https://bsky.social", "me.bsky.social", "bad", session)
    with pytest.raises(BlueskyError, match="login failed"):
        client.login()
    assert len(session.requests) == 1


def test_expired_token_is_refreshed_once_and_the_call_repeated():
    session = FakeSession(
        [
            FakeResponse(200, _SESSION_BODY),
            FakeResponse(400, {"error": "ExpiredToken"}),
            FakeResponse(200, {"accessJwt": "access-2", "refreshJwt": "refresh-2"}),
            FakeResponse(200, {"posts": [], "cursor": None}),
        ]
    )
    client = BlueskyClient("https://bsky.social", "me.bsky.social", "pw", session)
    client.login()
    assert client.get("app.bsky.feed.searchPosts", {"q": "x"}) == {
        "posts": [],
        "cursor": None,
    }
    refresh = session.requests[2]
    assert refresh[1].endswith("/xrpc/com.atproto.server.refreshSession")
    assert refresh[2]["headers"]["Authorization"] == "Bearer refresh-1"
    assert session.requests[3][2]["headers"]["Authorization"] == "Bearer access-2"


def test_other_client_errors_are_not_retried():
    session = FakeSession(
        [
            FakeResponse(200, _SESSION_BODY),
            FakeResponse(400, {"error": "InvalidRequest"}),
        ]
    )
    client = BlueskyClient("https://bsky.social", "me.bsky.social", "pw", session)
    client.login()
    with pytest.raises(BlueskyError, match="InvalidRequest"):
        client.get("app.bsky.feed.searchPosts", {"q": "x"})
