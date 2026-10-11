"""Steam reviews collector entry point.

Pulls user reviews for one Steam app, newest first, and writes gzipped
JSONL batches to the raw archive bucket — the same record shape and the
same destination layout as the YouTube collector.

The store review endpoint needs no key, no registration and no quota
application, which is why Steam is the project's second source
(docs/adr/0001-steam-replaces-reddit-as-second-source.md). It is also
undocumented, so this collector is deliberately polite: one page at a
time, a pause between pages, an honest user agent, and a hard page cap.

Run as a module::

    python -m collectors.steam.main

Configuration comes entirely from environment variables (see the README
in this directory).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests

from collectors.common import (
    Event,
    build_record,
    hash_author,
    load_events,
    resolve_event,
    write_batch,
)
from collectors.common.retry import retry_transient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("collectors.steam")

SOURCE = "steam"
REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
# The endpoint's own maximum.
PAGE_SIZE = 100
# Records per GCS object, as in the YouTube collector.
BATCH_SIZE = 500
# Safety cap on one run. 100 reviews per page, and the studied release has
# ~280,000 reviews, so a full history walk needs ~2,800 pages — see the
# README on why a historical window cannot be fetched directly.
DEFAULT_MAX_PAGES = 3000
DEFAULT_PAGE_SLEEP_SECONDS = 0.5
# EVENT_ID value that turns on per-record tagging.
AUTO_EVENT_ID = "auto"
# Records whose date falls near no event land here. The raw archive layout
# allows it: {source}/{event_id_or_general}/...
GENERAL_EVENT_ID = "general"
DEFAULT_EVENT_WINDOW_DAYS = 3.0
# Identifies the client honestly, as the ADR requires.
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
        event_id: Lifecycle event id this run targets.
        window_from: Inclusive start of the collection window (UTC).
        window_to: Exclusive end of the collection window (UTC).
        appid: Steam application id to collect reviews for.
        page_sleep_seconds: Pause between pages.
        max_pages: Safety cap on pages fetched in one run.
        event_window_days: Half-width, in days, of the window around each
            lifecycle event used when ``event_id`` is ``auto``.
    """

    target_bucket: str
    salt: str
    event_id: str
    window_from: datetime
    window_to: datetime
    appid: str
    page_sleep_seconds: float
    max_pages: int
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
    if not value:
        raise ValueError(f"Required environment variable {name} is unset or empty.")
    return value


def _parse_iso_utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime.

    Args:
        value: ISO 8601 string, with optional trailing ``Z``.

    Returns:
        A timezone-aware :class:`datetime` in UTC.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


def load_config() -> RunConfig:
    """Build the run configuration from environment variables.

    Returns:
        The resolved :class:`RunConfig`.

    Raises:
        ValueError: If a required variable is missing or malformed.
    """
    page_sleep = _float_env("STEAM_PAGE_SLEEP_SECONDS", DEFAULT_PAGE_SLEEP_SECONDS)
    if page_sleep < 0:
        raise ValueError("STEAM_PAGE_SLEEP_SECONDS must not be negative.")
    max_pages = int(_float_env("STEAM_MAX_PAGES", DEFAULT_MAX_PAGES))
    if max_pages <= 0:
        raise ValueError("STEAM_MAX_PAGES must be positive.")
    event_window_days = _float_env("EVENT_WINDOW_DAYS", DEFAULT_EVENT_WINDOW_DAYS)
    if event_window_days <= 0:
        raise ValueError("EVENT_WINDOW_DAYS must be positive.")

    return RunConfig(
        target_bucket=_require_env("TARGET_BUCKET"),
        salt=_require_env("AUTHOR_HASH_SALT"),
        event_id=_require_env("EVENT_ID"),
        window_from=_parse_iso_utc(_require_env("WINDOW_FROM")),
        window_to=_parse_iso_utc(_require_env("WINDOW_TO")),
        appid=_require_env("STEAM_APPID"),
        page_sleep_seconds=page_sleep,
        max_pages=max_pages,
        event_window_days=event_window_days,
    )


@retry_transient()
def fetch_page(
    appid: str,
    cursor: str,
    session: requests.Session,
) -> dict[str, Any]:
    """Fetch one page of reviews.

    ``filter=recent`` is what makes windowing possible: it returns reviews
    in descending ``timestamp_created`` order, so a run can stop as soon as
    it reads past the start of its window. The default (``all``) is sorted
    by helpfulness and would have to read everything.

    Args:
        appid: Steam application id.
        cursor: Pagination cursor; ``*`` for the first page.
        session: HTTP session carrying the user agent.

    Returns:
        The decoded JSON body.

    Raises:
        RuntimeError: If the endpoint reports failure.
    """
    response = session.get(
        REVIEWS_URL.format(appid=appid),
        params={
            "json": "1",
            "filter": "recent",
            "language": "all",
            "purchase_type": "all",
            "review_type": "all",
            "num_per_page": str(PAGE_SIZE),
            "cursor": cursor,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    if payload.get("success") != 1:
        raise RuntimeError(
            f"Steam review endpoint reported failure for appid {appid} "
            f"(success={payload.get('success')!r})."
        )
    return payload


def event_tag_for(
    created: datetime,
    events: dict[str, Event],
    window_days: float,
) -> str:
    """Return the lifecycle event a review belongs to, by its own date.

    Steam's endpoint can only be read newest-first, so a historical window
    is reached by walking back through everything newer — ~2,800 pages for
    this release. Doing that once per event is absurd; one walk tags each
    review by its own date instead.

    Args:
        created: The review's creation time (UTC).
        events: Configured events, keyed by id.
        window_days: Half-width of the window around each event date.

    Returns:
        The id of the nearest event within the window, or
        :data:`GENERAL_EVENT_ID` when the review falls near none. Ties go to
        the earlier event date, then to the smaller id, so tagging is
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


def review_record(
    review: dict[str, Any],
    config: RunConfig,
    event_tag: str | None = None,
) -> dict[str, Any]:
    """Map one Steam review onto the shared collector record.

    The author's ``steamid`` is hashed here and nothing else about them is
    kept: ``personaname`` and ``profile_url`` never reach GCS. Steam's own
    ``language`` field is not used — it carries names like ``schinese``,
    not the ISO codes the schema holds — so language is detected the same
    way as for YouTube, and Dataflow overrides it anyway.

    Args:
        review: One element of the endpoint's ``reviews`` array.
        config: The active run configuration.
        event_tag: Event id to tag this record with. Defaults to the run's
            ``EVENT_ID``, which is what a narrow single-event run wants.

    Returns:
        A collector record dict.
    """
    author = review.get("author") or {}
    return build_record(
        record_id=f"{SOURCE}:{review['recommendationid']}",
        source=SOURCE,
        author_hash=hash_author(str(author.get("steamid", "[unknown]")), config.salt),
        text=review.get("review") or "",
        score=int(review.get("votes_up", 0)),
        context_id=config.appid,
        event_tag=event_tag or config.event_id,
        created_utc_epoch=float(review["timestamp_created"]),
        # Reviews are flat: there are no replies to collect.
        parent_id=None,
        voted_up=bool(review.get("voted_up", False)),
    )


def collect(config: RunConfig, session: requests.Session | None = None) -> int:
    """Run the collection and write batches to GCS.

    Args:
        config: The active run configuration.
        session: Optional injected HTTP session (tests).

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

    owned_session = session is None
    http = session or requests.Session()
    http.headers.setdefault("User-Agent", USER_AGENT)

    # One buffer per event tag: a page can straddle two events, and each
    # tag is its own prefix in the raw archive.
    buffers: dict[str, list[dict[str, Any]]] = {}
    buffered = 0
    total_written = 0

    def flush(tag: str | None = None) -> None:
        nonlocal total_written, buffered
        tags = [tag] if tag is not None else list(buffers)
        for one in tags:
            records = buffers.get(one) or []
            if not records:
                continue
            uri = write_batch(records, SOURCE, one, bucket=config.target_bucket)
            logger.info("Wrote %d records to %s", len(records), uri)
            total_written += len(records)
            buffered -= len(records)
            records.clear()

    try:
        cursor = "*"
        seen_cursors: set[str] = set()
        reached_window_start = False
        pages_read = 0

        for page in range(1, config.max_pages + 1):
            pages_read = page
            payload = fetch_page(config.appid, cursor, http)
            reviews = payload.get("reviews") or []
            if not reviews:
                logger.info("Page %d came back empty; collection complete.", page)
                break

            for review in reviews:
                created = datetime.fromtimestamp(
                    float(review["timestamp_created"]), tz=UTC
                )
                if created < config.window_from:
                    # Descending order: everything after this is older.
                    reached_window_start = True
                    break
                if created >= config.window_to:
                    continue
                tag = (
                    event_tag_for(created, events, config.event_window_days)
                    if config.auto_tagging
                    else config.event_id
                )
                buffers.setdefault(tag, []).append(
                    review_record(review, config, event_tag=tag)
                )
                buffered += 1
                if len(buffers[tag]) >= BATCH_SIZE:
                    flush(tag)

            if reached_window_start:
                logger.info("Reached the start of the window on page %d.", page)
                break

            next_cursor = str(payload.get("cursor") or "")
            if not next_cursor or next_cursor in seen_cursors:
                logger.info("Cursor did not advance on page %d; stopping.", page)
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor

            # Progress matters here: a full history walk is thousands of
            # pages, and a silent job for half an hour is indistinguishable
            # from a stuck one.
            if page % 100 == 0:
                logger.info(
                    "Page %d: %d written, %d buffered, oldest read %s.",
                    page,
                    total_written,
                    buffered,
                    created.isoformat(),
                )
            if config.page_sleep_seconds:
                time.sleep(config.page_sleep_seconds)

        if not reached_window_start and pages_read >= config.max_pages:
            logger.warning(
                "Hit the %d-page cap before reaching the start of the window. "
                "Raise STEAM_MAX_PAGES or narrow the window; the records "
                "written so far are complete from the newest end down.",
                config.max_pages,
            )

        flush()
    finally:
        if owned_session:
            http.close()

    return total_written


def main() -> None:
    """Program entry point: load config, collect, and report."""
    config = load_config()
    logger.info(
        "Starting Steam collection for appid=%s event=%s window=%s..%s bucket=%s",
        config.appid,
        config.event_id,
        config.window_from.isoformat(),
        config.window_to.isoformat(),
        config.target_bucket,
    )
    total = collect(config)
    logger.info("Steam collection finished: %d records written.", total)


if __name__ == "__main__":
    main()
