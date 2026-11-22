"""Bluesky posts collector entry point.

Searches public Bluesky posts for one release and writes gzipped JSONL
batches to the raw archive bucket — the same record shape and the same
destination layout as the YouTube and Steam collectors.

Bluesky is the second source for releases without a Steam page
(docs/adr/0005-bluesky-as-second-source-for-gta-vi.md). The search
endpoint, ``app.bsky.feed.searchPosts``, takes ``since`` / ``until``, so
one code path serves both history (a long window, sliced) and live
collection (a short look-back window on a schedule).

Search needs an account session: anonymous requests get one page and
then 403. The collector logs in once per run with an app password and
refreshes the token if it expires mid-run.

Run as a module::

    python -m collectors.bluesky.main

Configuration comes entirely from environment variables (see the README
in this directory).
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from collectors.common import (
    Event,
    build_record,
    hash_author,
    load_events,
    resolve_event,
    write_batch,
)
from collectors.common.events_config import event_tag_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("collectors.bluesky")

SOURCE = "bluesky"
DEFAULT_PDS_URL = "https://bsky.social"
# Routes app.bsky.* calls made to the PDS on to Bluesky's AppView, which
# is what actually serves search.
APPVIEW_PROXY = "did:web:api.bsky.app#bsky_appview"
SEARCH_NSID = "app.bsky.feed.searchPosts"
# Post ids are salted hashes of the post URI. The domain prefix keeps them
# from ever coinciding with an author hash of the same string; 32 hex
# characters (128 bits) make collisions irrelevant at any realistic volume.
POST_ID_DOMAIN = "bluesky-post:"
POST_ID_HEX_LENGTH = 32
# The endpoint's own maximum.
PAGE_SIZE = 100
# Records per GCS object, as in the other collectors.
BATCH_SIZE = 500
# A long window is searched as consecutive slices, newest first. Search
# results are cursor-paginated to a finite depth, so one huge window can
# silently end early; slices keep each result stream short enough to be
# read to its end. Launch-week hours may need far smaller slices than this.
DEFAULT_SLICE_MINUTES = 360.0
DEFAULT_MAX_PAGES_PER_SLICE = 100
DEFAULT_PAGE_SLEEP_SECONDS = 1.0
DEFAULT_EVENT_WINDOW_DAYS = 3.0
# EVENT_ID value that turns on per-record tagging.
AUTO_EVENT_ID = "auto"
# Retries for one page.
RETRY_ATTEMPTS = 6
RETRY_MAX_WAIT_SECONDS = 300.0
# Identifies the client honestly.
USER_AGENT = (
    "pop-vibe-check/1.0 (engineering thesis; "
    "https://github.com/MarcinMazuro/pop-vibe-check)"
)


@dataclass(frozen=True)
class RunConfig:
    """Resolved configuration for a single collector run.

    Attributes:
        target_bucket: Destination GCS bucket name.
        salt: Author-hash salt.
        event_id: Lifecycle event id this run targets, or ``auto`` to tag
            each post by its own date.
        window_from: Inclusive start of the collection window (UTC).
        window_to: Exclusive end of the collection window (UTC).
        handle: Account handle (or DID) the collector logs in as.
        app_password: App password for that account.
        pds_url: PDS the account lives on; ``createSession`` goes here.
        queries: Search queries. A post matching several is written once.
        slice_minutes: Width of one search slice.
        max_pages_per_slice: Safety cap on pages read for one slice.
        page_sleep_seconds: Pause between pages.
        event_window_days: Half-width of the window around each event,
            for ``auto`` tagging.
    """

    target_bucket: str
    salt: str
    event_id: str
    window_from: datetime
    window_to: datetime
    handle: str
    app_password: str
    pds_url: str
    queries: tuple[str, ...]
    slice_minutes: float
    max_pages_per_slice: int
    page_sleep_seconds: float
    event_window_days: float

    @property
    def auto_tagging(self) -> bool:
        """Whether each record is tagged by its own date rather than per run."""
        return self.event_id == AUTO_EVENT_ID


def _require_env(name: str) -> str:
    """Return a required environment variable or fail loudly.

    Args:
        name: Environment variable name.

    Returns:
        The variable's value.

    Raises:
        ValueError: If the variable is unset or empty.
    """
    value = os.environ.get(name)
    if not value or not value.strip():
        raise ValueError(f"Required environment variable {name} is unset or empty.")
    return value.strip()


def _parse_iso_utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime.

    Args:
        value: ISO 8601 string, with optional trailing ``Z``.

    Returns:
        A timezone-aware :class:`datetime` in UTC.
    """
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso_z(moment: datetime) -> str:
    """Format a datetime as the ISO 8601 UTC form the API expects.

    Args:
        moment: A timezone-aware datetime.

    Returns:
        E.g. ``2026-11-19T00:00:00Z``.
    """
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _float_env(name: str, default: float) -> float:
    """Read a numeric environment variable with a default.

    Args:
        name: Environment variable name.
        default: Value used when the variable is unset or empty.

    Returns:
        The parsed number.

    Raises:
        ValueError: If the value is set but not numeric.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got '{raw}'.") from exc


def resolve_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Resolve the collection window from the environment.

    Either an explicit ``WINDOW_FROM`` / ``WINDOW_TO`` pair (history), or
    ``WINDOW_LOOKBACK_MINUTES`` (live): the window then ends now and starts
    that many minutes earlier. A scheduler can only pass fixed
    environment overrides, so the look-back form is what lets one static
    schedule collect "since the last run". Overlapping windows are
    harmless — ids are stable and the staging MERGE keys on them.

    Args:
        now: Override for the current time (tests).

    Returns:
        ``(window_from, window_to)``, both UTC.

    Raises:
        ValueError: If both forms or neither are given, or the window is
            empty.
    """
    raw_from = os.environ.get("WINDOW_FROM", "").strip()
    raw_to = os.environ.get("WINDOW_TO", "").strip()
    raw_lookback = os.environ.get("WINDOW_LOOKBACK_MINUTES", "").strip()

    if raw_lookback and (raw_from or raw_to):
        raise ValueError(
            "Set either WINDOW_LOOKBACK_MINUTES or WINDOW_FROM/WINDOW_TO, not both."
        )
    if raw_lookback:
        lookback = _float_env("WINDOW_LOOKBACK_MINUTES", 0.0)
        if lookback <= 0:
            raise ValueError("WINDOW_LOOKBACK_MINUTES must be positive.")
        window_to = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
        return window_to - timedelta(minutes=lookback), window_to
    if not raw_from or not raw_to:
        raise ValueError(
            "Set WINDOW_FROM and WINDOW_TO, or WINDOW_LOOKBACK_MINUTES for a "
            "window ending now."
        )
    window_from, window_to = _parse_iso_utc(raw_from), _parse_iso_utc(raw_to)
    if window_from >= window_to:
        raise ValueError(
            f"WINDOW_FROM ({raw_from}) must be earlier than WINDOW_TO ({raw_to})."
        )
    return window_from, window_to


def parse_queries(raw: str) -> tuple[str, ...]:
    """Split ``BLUESKY_QUERIES`` into individual search queries.

    Queries are separated by ``;`` — commas and spaces occur inside
    queries (``"GTA 6"``), semicolons practically never do.

    Args:
        raw: The variable's value.

    Returns:
        The non-empty queries, in order, without duplicates.

    Raises:
        ValueError: If no query is left.
    """
    queries: list[str] = []
    for part in raw.split(";"):
        query = part.strip()
        if query and query not in queries:
            queries.append(query)
    if not queries:
        raise ValueError("BLUESKY_QUERIES holds no query.")
    return tuple(queries)


def load_config(now: datetime | None = None) -> RunConfig:
    """Build the run configuration from environment variables.

    Args:
        now: Override for the current time (tests).

    Returns:
        The resolved :class:`RunConfig`.

    Raises:
        ValueError: If a required variable is missing or malformed.
    """
    slice_minutes = _float_env("BLUESKY_SLICE_MINUTES", DEFAULT_SLICE_MINUTES)
    if slice_minutes <= 0:
        raise ValueError("BLUESKY_SLICE_MINUTES must be positive.")
    max_pages = int(
        _float_env("BLUESKY_MAX_PAGES_PER_SLICE", DEFAULT_MAX_PAGES_PER_SLICE)
    )
    if max_pages <= 0:
        raise ValueError("BLUESKY_MAX_PAGES_PER_SLICE must be positive.")
    page_sleep = _float_env("BLUESKY_PAGE_SLEEP_SECONDS", DEFAULT_PAGE_SLEEP_SECONDS)
    if page_sleep < 0:
        raise ValueError("BLUESKY_PAGE_SLEEP_SECONDS must not be negative.")
    event_window_days = _float_env("EVENT_WINDOW_DAYS", DEFAULT_EVENT_WINDOW_DAYS)
    if event_window_days <= 0:
        raise ValueError("EVENT_WINDOW_DAYS must be positive.")

    window_from, window_to = resolve_window(now)
    return RunConfig(
        target_bucket=_require_env("TARGET_BUCKET"),
        salt=_require_env("AUTHOR_HASH_SALT"),
        event_id=_require_env("EVENT_ID"),
        window_from=window_from,
        window_to=window_to,
        handle=_require_env("BLUESKY_HANDLE"),
        app_password=_require_env("BLUESKY_APP_PASSWORD"),
        pds_url=(os.environ.get("BLUESKY_PDS_URL") or DEFAULT_PDS_URL)
        .strip()
        .rstrip("/"),
        queries=parse_queries(_require_env("BLUESKY_QUERIES")),
        slice_minutes=slice_minutes,
        max_pages_per_slice=max_pages,
        page_sleep_seconds=page_sleep,
        event_window_days=event_window_days,
    )


def window_slices(
    window_from: datetime, window_to: datetime, slice_minutes: float
) -> list[tuple[datetime, datetime]]:
    """Cut a window into consecutive slices, newest first.

    Newest first so that a run cut short (timeout, page cap) has already
    written the most recent data, which is what live collection cares
    about and what history can re-fetch later.

    Args:
        window_from: Inclusive window start.
        window_to: Exclusive window end.
        slice_minutes: Width of each slice; the oldest may be narrower.

    Returns:
        ``(since, until)`` pairs covering the window exactly once.
    """
    step = timedelta(minutes=slice_minutes)
    slices: list[tuple[datetime, datetime]] = []
    until = window_to
    while until > window_from:
        since = max(window_from, until - step)
        slices.append((since, until))
        until = since
    return slices


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------


class BlueskyError(RuntimeError):
    """A non-retryable error reported by the Bluesky API."""


def _status_code(exc: BaseException) -> int | None:
    """Best-effort HTTP status code from a requests exception."""
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def _is_retryable(exc: BaseException) -> bool:
    """Return whether a request should be retried: 429, 5xx, connection errors."""
    if isinstance(exc, BlueskyError):
        return False
    code = _status_code(exc)
    if code is not None:
        return code == 429 or 500 <= code < 600
    return isinstance(exc, requests.exceptions.RequestException)


def _rate_limit_reset_wait(exc: BaseException | None) -> float | None:
    """Seconds until the server's rate-limit window resets, when it says.

    Bluesky sends ``ratelimit-reset`` as a Unix timestamp on 429s.

    Args:
        exc: The raised exception.

    Returns:
        Seconds to wait, or ``None`` when there is no usable header.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    raw = headers.get("ratelimit-reset") or headers.get("RateLimit-Reset")
    if not raw:
        return None
    try:
        return max(0.0, float(raw) - time.time())
    except (TypeError, ValueError):
        return None


def _retry_wait(retry_state: Any) -> float:
    """Wait between attempts: the server's reset time, else backoff."""
    backoff = float(
        wait_exponential(multiplier=2.0, min=2.0, max=RETRY_MAX_WAIT_SECONDS)(
            retry_state
        )
    )
    outcome = retry_state.outcome
    exc = outcome.exception() if outcome is not None else None
    requested = _rate_limit_reset_wait(exc)
    if requested is not None:
        return min(max(requested + 1.0, backoff), RETRY_MAX_WAIT_SECONDS)
    return backoff


def _error_name(response: requests.Response) -> str:
    """The XRPC ``error`` field of a failed response, if any."""
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("error") or "") if isinstance(body, dict) else ""


class BlueskyClient:
    """A logged-in XRPC client: one session per run, refreshed on expiry.

    The PDS rate-limits ``createSession`` per account (on the order of a
    few hundred a day), so the client logs in once and refreshes rather
    than logging in again.
    """

    def __init__(
        self,
        pds_url: str,
        handle: str,
        app_password: str,
        session: requests.Session | None = None,
    ) -> None:
        """Prepare the client; nothing is sent until :meth:`login`.

        Args:
            pds_url: The account's PDS (``createSession`` endpoint).
            handle: Account handle or DID.
            app_password: App password — never the account password.
            session: Optional injected HTTP session (tests).
        """
        self._entry_url = pds_url.rstrip("/")
        self._service_url = self._entry_url
        self._handle = handle
        self._app_password = app_password
        self._http = session or requests.Session()
        self._owned = session is None
        self._http.headers.setdefault("User-Agent", USER_AGENT)
        self._access_jwt = ""
        self._refresh_jwt = ""

    def close(self) -> None:
        """Close the HTTP session if this client created it."""
        if self._owned:
            self._http.close()

    @staticmethod
    def _pds_from_did_doc(did_doc: Any) -> str | None:
        """The account's own PDS endpoint from its DID document, if present.

        Logging in through the ``bsky.social`` entryway works for every
        account hosted by Bluesky, but later calls belong on the PDS that
        actually holds the account.
        """
        if not isinstance(did_doc, dict):
            return None
        for service in did_doc.get("service") or []:
            if (
                isinstance(service, dict)
                and str(service.get("id", "")).endswith("#atproto_pds")
                and service.get("serviceEndpoint")
            ):
                return str(service["serviceEndpoint"]).rstrip("/")
        return None

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=_retry_wait,
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        reraise=True,
    )
    def login(self) -> None:
        """Create a session with the app password.

        Raises:
            BlueskyError: If the credentials are rejected.
        """
        response = self._http.post(
            f"{self._entry_url}/xrpc/com.atproto.server.createSession",
            json={"identifier": self._handle, "password": self._app_password},
            timeout=30,
        )
        if response.status_code in (400, 401):
            raise BlueskyError(
                f"Bluesky login failed for {self._handle} "
                f"({response.status_code} {_error_name(response) or 'no error name'}). "
                "Check BLUESKY_HANDLE and the app password in Secret Manager."
            )
        response.raise_for_status()
        body = response.json()
        self._access_jwt = str(body["accessJwt"])
        self._refresh_jwt = str(body["refreshJwt"])
        self._service_url = self._pds_from_did_doc(body.get("didDoc")) or (
            self._entry_url
        )
        logger.info("Logged in to Bluesky; requests go to %s.", self._service_url)

    def _refresh(self) -> None:
        """Swap the refresh token for a new pair; log in again if that fails."""
        response = self._http.post(
            f"{self._service_url}/xrpc/com.atproto.server.refreshSession",
            headers={"Authorization": f"Bearer {self._refresh_jwt}"},
            timeout=30,
        )
        if response.ok:
            body = response.json()
            self._access_jwt = str(body["accessJwt"])
            self._refresh_jwt = str(body["refreshJwt"])
            logger.info("Refreshed the Bluesky session.")
            return
        logger.warning(
            "Session refresh failed (%d %s); logging in again.",
            response.status_code,
            _error_name(response),
        )
        self.login()

    def _get_once(self, nsid: str, params: dict[str, Any]) -> requests.Response:
        return self._http.get(
            f"{self._service_url}/xrpc/{nsid}",
            params=params,
            headers={
                "Authorization": f"Bearer {self._access_jwt}",
                "atproto-proxy": APPVIEW_PROXY,
            },
            timeout=30,
        )

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=_retry_wait,
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        reraise=True,
    )
    def get(self, nsid: str, params: dict[str, Any]) -> dict[str, Any]:
        """Authenticated XRPC query, refreshing the session once on expiry.

        Args:
            nsid: Method id, e.g. ``app.bsky.feed.searchPosts``.
            params: Query parameters.

        Returns:
            The decoded JSON body.

        Raises:
            BlueskyError: On a non-retryable API error.
        """
        if not self._access_jwt:
            raise BlueskyError("Not logged in; call login() first.")
        response = self._get_once(nsid, params)
        if response.status_code in (400, 401) and _error_name(response) in (
            "ExpiredToken",
            "InvalidToken",
        ):
            self._refresh()
            response = self._get_once(nsid, params)
        if response.status_code == 429:
            logger.warning("Rate limited by Bluesky; backing off.")
        if 400 <= response.status_code < 500 and response.status_code != 429:
            raise BlueskyError(
                f"{nsid} failed: {response.status_code} "
                f"{_error_name(response)} {response.text[:300]}"
            )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload


# ----------------------------------------------------------------------------
# Records
# ----------------------------------------------------------------------------


def _parse_at_uri(uri: str) -> tuple[str, str]:
    """Split ``at://<did>/<collection>/<rkey>`` into ``(did, rkey)``.

    Args:
        uri: An AT URI of a post.

    Returns:
        The repository DID and the record key.

    Raises:
        ValueError: If the URI does not have that shape.
    """
    if not uri.startswith("at://"):
        raise ValueError(f"Not an AT URI: {uri!r}.")
    parts = uri[len("at://") :].split("/")
    if len(parts) != 3 or not parts[0] or not parts[2]:
        raise ValueError(f"Unexpected AT URI shape: {uri!r}.")
    return parts[0], parts[2]


def pseudonymous_post_id(uri: str, salt: str) -> str:
    """Stable record id for a post that reveals nothing about its author.

    A post's AT URI embeds the author's DID — a permanent identifier of
    the account, personal data under the same reasoning that hashes
    handles. Nor can the id carry the author hash: ``id`` is exposed by the
    reporting layer, which must not let a reader group posts by author.
    The id is therefore a salted hash of the whole URI: stable across runs
    (same salt), unlinkable to the author without the salt, and computable
    for a reply's parent from the parent's URI alone, so threads can still
    be rebuilt from ``parent_id``.

    Args:
        uri: The post's AT URI.
        salt: Author-hash salt (reused: one secret, one rotation decision).

    Returns:
        ``bluesky:`` followed by 32 hex characters.

    Raises:
        ValueError: If ``uri`` is not a post AT URI.
    """
    _parse_at_uri(uri)
    digest = hashlib.sha256(f"{POST_ID_DOMAIN}{uri}{salt}".encode()).hexdigest()
    return f"{SOURCE}:{digest[:POST_ID_HEX_LENGTH]}"


def post_created(post: dict[str, Any]) -> datetime:
    """The post's time on the shared ``created_utc`` axis.

    ``record.createdAt`` is set by the author's client and can claim any
    date; ``indexedAt`` is when Bluesky's AppView saw it. The earlier of
    the two is used, which is also what search's ``since`` / ``until``
    filter on — so a backdated post is placed where search placed it, and
    a future-dated one cannot jump ahead of the stream.

    Args:
        post: One element of the search response's ``posts`` array.

    Returns:
        A timezone-aware UTC datetime.
    """
    record = post.get("record") or {}
    candidates = []
    for raw in (record.get("createdAt"), post.get("indexedAt")):
        if raw:
            try:
                candidates.append(_parse_iso_utc(str(raw)))
            except ValueError:
                continue
    if not candidates:
        raise ValueError(f"Post {post.get('uri')!r} carries no usable timestamp.")
    return min(candidates)


def post_record(
    post: dict[str, Any],
    config: RunConfig,
    event_tag: str,
    query: str,
) -> dict[str, Any]:
    """Map one Bluesky post onto the shared collector record.

    Only the salted hash of the author's DID is kept, in ``author_hash``.
    Handle, display name, avatar and DID never reach GCS, and the record id
    and ``parent_id`` are salted hashes of post URIs that do not carry the
    author either (see :func:`pseudonymous_post_id`).

    The author's own ``langs`` tag, when present, is used as the advisory
    language; otherwise language is detected as for the other sources.
    Dataflow writes the authoritative value either way.

    Args:
        post: One element of the search response's ``posts`` array.
        config: The active run configuration.
        event_tag: Event id to tag this record with.
        query: The search query that found the post, kept as
            ``context_id`` — the closest Bluesky analogue of a video id.

    Returns:
        A collector record dict.
    """
    record = post.get("record") or {}
    did, _ = _parse_at_uri(str(post["uri"]))
    parent_uri = ((record.get("reply") or {}).get("parent") or {}).get("uri")
    parent_id = (
        pseudonymous_post_id(str(parent_uri), config.salt) if parent_uri else None
    )
    langs = record.get("langs") or []
    language = str(langs[0]) if langs else None
    return build_record(
        record_id=pseudonymous_post_id(str(post["uri"]), config.salt),
        source=SOURCE,
        author_hash=hash_author(did, config.salt),
        text=str(record.get("text") or ""),
        score=int(post.get("likeCount") or 0),
        context_id=query,
        event_tag=event_tag,
        created_utc_epoch=post_created(post).timestamp(),
        parent_id=parent_id,
        language=language,
    )


# ----------------------------------------------------------------------------
# Collection
# ----------------------------------------------------------------------------


def collect(config: RunConfig, client: BlueskyClient | None = None) -> int:
    """Run the collection and write batches to GCS.

    Args:
        config: The active run configuration.
        client: Optional injected client (tests). When omitted, one is
            built and logged in.

    Returns:
        The total number of records written.
    """
    events: dict[str, Event] = {}
    if config.auto_tagging:
        events = load_events()
        logger.info(
            "Auto-tagging against %d events, +/- %.1f days.",
            len(events),
            config.event_window_days,
        )
    else:
        resolve_event(config.event_id)  # Fail loudly on an unknown event id.

    owned_client = client is None
    api = client or BlueskyClient(config.pds_url, config.handle, config.app_password)
    if owned_client:
        api.login()

    buffers: dict[str, list[dict[str, Any]]] = {}
    seen_ids: set[str] = set()
    total_written = 0
    skipped_empty = 0
    capped_slices = 0

    def flush(tag: str | None = None) -> None:
        nonlocal total_written
        for one in [tag] if tag is not None else list(buffers):
            records = buffers.get(one) or []
            if not records:
                continue
            uri = write_batch(records, SOURCE, one, bucket=config.target_bucket)
            logger.info("Wrote %d records to %s", len(records), uri)
            total_written += len(records)
            records.clear()

    slices = window_slices(config.window_from, config.window_to, config.slice_minutes)
    logger.info(
        "%d queries x %d slices of up to %.0f minutes.",
        len(config.queries),
        len(slices),
        config.slice_minutes,
    )

    try:
        for since, until in slices:
            for query in config.queries:
                cursor: str | None = None
                pages = 0
                slice_posts = 0
                while True:
                    params: dict[str, Any] = {
                        "q": query,
                        "sort": "latest",
                        "since": _iso_z(since),
                        "until": _iso_z(until),
                        "limit": PAGE_SIZE,
                    }
                    if cursor:
                        params["cursor"] = cursor
                    payload = api.get(SEARCH_NSID, params)
                    pages += 1
                    posts = payload.get("posts") or []
                    slice_posts += len(posts)

                    for post in posts:
                        created = post_created(post)
                        # The API filters on the same axis; this guards the
                        # slice edges so adjacent slices never both keep a post.
                        if not (since <= created < until):
                            continue
                        record_id = pseudonymous_post_id(str(post["uri"]), config.salt)
                        if record_id in seen_ids:
                            continue
                        seen_ids.add(record_id)
                        text = str((post.get("record") or {}).get("text") or "")
                        if not text.strip():
                            # Image-only posts: nothing for a text model.
                            skipped_empty += 1
                            continue
                        tag = (
                            event_tag_for(created, events, config.event_window_days)
                            if config.auto_tagging
                            else config.event_id
                        )
                        buffers.setdefault(tag, []).append(
                            post_record(post, config, tag, query)
                        )
                        if len(buffers[tag]) >= BATCH_SIZE:
                            flush(tag)

                    next_cursor = payload.get("cursor")
                    if not posts or not next_cursor or next_cursor == cursor:
                        break
                    if pages >= config.max_pages_per_slice:
                        capped_slices += 1
                        logger.warning(
                            "Query %r hit the %d-page cap in slice %s..%s; "
                            "older posts in that slice were not read. Lower "
                            "BLUESKY_SLICE_MINUTES for this period.",
                            query,
                            config.max_pages_per_slice,
                            _iso_z(since),
                            _iso_z(until),
                        )
                        break
                    cursor = str(next_cursor)
                    if config.page_sleep_seconds:
                        time.sleep(config.page_sleep_seconds)

                logger.info(
                    "Slice %s..%s query %r: %d posts over %d pages.",
                    _iso_z(since),
                    _iso_z(until),
                    query,
                    slice_posts,
                    pages,
                )
            # Each finished slice is durable before the next one starts.
            flush()
    finally:
        flush()
        if owned_client:
            api.close()

    logger.info(
        "Done: %d written, %d unique posts seen, %d without text skipped, "
        "%d capped slices.",
        total_written,
        len(seen_ids),
        skipped_empty,
        capped_slices,
    )
    return total_written


def main() -> None:
    """Program entry point: load config, collect, and report."""
    config = load_config()
    logger.info(
        "Starting Bluesky collection as %s: event=%s window=%s..%s queries=%s "
        "bucket=%s",
        config.handle,
        config.event_id,
        _iso_z(config.window_from),
        _iso_z(config.window_to),
        list(config.queries),
        config.target_bucket,
    )
    total = collect(config)
    logger.info("Bluesky collection finished: %d records written.", total)


if __name__ == "__main__":
    main()
