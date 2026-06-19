"""Reddit collector entry point.

Pulls posts and comments about *Clair Obscur: Expedition 33* from a fixed set of
subreddits for a given lifecycle event and time window, then writes gzipped JSONL
batches to the raw archive bucket.

Run as a module::

    python -m collectors.reddit.main

Configuration is taken entirely from environment variables (see the README in
this directory).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import praw

from collectors.common import build_record, hash_author, resolve_event, write_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("collectors.reddit")

SOURCE = "reddit"
SEARCH_QUERY = "clair obscur OR expedition 33"
SUBREDDITS = ["ClairObscurExpedition33", "JRPG", "Games", "gaming"]

# Reddit search returns at most ~1000 results per query, so the window is walked
# in narrow slices to stay well under that ceiling.
SLICE_HOURS = 6
# Max comment depth to descend (0 = top-level, 1 = reply, 2 = reply-to-reply).
MAX_COMMENT_DEPTH = 2
# Records per GCS object.
BATCH_SIZE = 500
# Politeness pause between subreddit/slice queries (Reddit OAuth ~100 req/min).
QUERY_PAUSE_SECONDS = 1.0


@dataclass(frozen=True)
class RunConfig:
    """Resolved configuration for a single collector run.

    Attributes:
        target_bucket: Destination GCS bucket name.
        salt: Author-hash salt.
        event_id: Lifecycle event id this run targets.
        window_from: Inclusive start of the collection window (UTC).
        window_to: Exclusive end of the collection window (UTC).
        client_id: Reddit OAuth client id.
        client_secret: Reddit OAuth client secret.
        user_agent: Reddit user-agent string.
    """

    target_bucket: str
    salt: str
    event_id: str
    window_from: datetime
    window_to: datetime
    client_id: str
    client_secret: str
    user_agent: str


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


def load_config() -> RunConfig:
    """Build the run configuration from environment variables.

    Returns:
        The resolved :class:`RunConfig`.

    Raises:
        ValueError: If any required variable is missing.
    """
    return RunConfig(
        target_bucket=_require_env("TARGET_BUCKET"),
        salt=_require_env("AUTHOR_HASH_SALT"),
        event_id=_require_env("EVENT_ID"),
        window_from=_parse_iso_utc(_require_env("WINDOW_FROM")),
        window_to=_parse_iso_utc(_require_env("WINDOW_TO")),
        client_id=_require_env("REDDIT_CLIENT_ID"),
        client_secret=_require_env("REDDIT_CLIENT_SECRET"),
        user_agent=_require_env("REDDIT_USER_AGENT"),
    )


def _time_slices(
    window_from: datetime, window_to: datetime
) -> Iterator[tuple[datetime, datetime]]:
    """Yield ``SLICE_HOURS``-wide sub-windows covering the full window.

    Args:
        window_from: Inclusive start of the window (UTC).
        window_to: Exclusive end of the window (UTC).

    Yields:
        ``(slice_start, slice_end)`` tuples in chronological order.
    """
    cursor = window_from
    step = timedelta(hours=SLICE_HOURS)
    while cursor < window_to:
        yield cursor, min(cursor + step, window_to)
        cursor += step


def _iter_comments(comment_forest: Any) -> Iterator[tuple[Any, int]]:
    """Walk a PRAW comment forest depth-first up to ``MAX_COMMENT_DEPTH``.

    Args:
        comment_forest: A PRAW ``CommentForest`` (``submission.comments``).

    Yields:
        ``(comment, depth)`` pairs where depth 0 is a top-level comment.
    """
    comment_forest.replace_more(limit=0)
    stack: list[tuple[Any, int]] = [(c, 0) for c in comment_forest]
    while stack:
        comment, depth = stack.pop()
        yield comment, depth
        if depth < MAX_COMMENT_DEPTH:
            stack.extend((reply, depth + 1) for reply in comment.replies)


def _post_record(submission: Any, config: RunConfig) -> dict[str, Any]:
    """Build a record for a Reddit submission (post).

    Args:
        submission: A PRAW ``Submission``.
        config: The active run configuration.

    Returns:
        A collector record dict.
    """
    author = submission.author.name if submission.author else "[deleted]"
    title = submission.title or ""
    body = submission.selftext or ""
    text = f"{title}\n\n{body}".strip()
    return build_record(
        record_id=f"{SOURCE}:{submission.fullname}",
        source=SOURCE,
        author_hash=hash_author(author, config.salt),
        text=text,
        score=int(submission.score),
        context_id=str(submission.subreddit.display_name),
        event_tag=config.event_id,
        created_utc_epoch=float(submission.created_utc),
        parent_id=None,
    )


def _comment_record(
    comment: Any, subreddit_name: str, config: RunConfig
) -> dict[str, Any]:
    """Build a record for a Reddit comment.

    Args:
        comment: A PRAW ``Comment``.
        subreddit_name: Display name of the parent subreddit (no ``r/``).
        config: The active run configuration.

    Returns:
        A collector record dict.
    """
    author = comment.author.name if comment.author else "[deleted]"
    return build_record(
        record_id=f"{SOURCE}:{comment.fullname}",
        source=SOURCE,
        author_hash=hash_author(author, config.salt),
        text=comment.body or "",
        score=int(comment.score),
        context_id=subreddit_name,
        event_tag=config.event_id,
        created_utc_epoch=float(comment.created_utc),
        parent_id=str(comment.parent_id),
    )


def collect(config: RunConfig, reddit: praw.Reddit) -> int:
    """Run the collection and write batches to GCS.

    Args:
        config: The active run configuration.
        reddit: An authenticated PRAW client.

    Returns:
        The total number of records written.
    """
    resolve_event(config.event_id)  # Fail loudly on an unknown event id.

    buffer: list[dict[str, Any]] = []
    total_written = 0

    def flush() -> None:
        nonlocal total_written
        if not buffer:
            return
        uri = write_batch(buffer, SOURCE, config.event_id, bucket=config.target_bucket)
        logger.info("Wrote %d records to %s", len(buffer), uri)
        total_written += len(buffer)
        buffer.clear()

    for subreddit_name in SUBREDDITS:
        subreddit = reddit.subreddit(subreddit_name)
        for slice_start, slice_end in _time_slices(
            config.window_from, config.window_to
        ):
            logger.info(
                "Searching r/%s for slice %s..%s",
                subreddit_name,
                slice_start.isoformat(),
                slice_end.isoformat(),
            )
            results = subreddit.search(
                SEARCH_QUERY, sort="new", time_filter="all", limit=None
            )
            for submission in results:
                created = datetime.fromtimestamp(float(submission.created_utc), tz=UTC)
                if not slice_start <= created < slice_end:
                    continue

                buffer.append(_post_record(submission, config))
                for comment, _depth in _iter_comments(submission.comments):
                    buffer.append(_comment_record(comment, subreddit_name, config))
                    if len(buffer) >= BATCH_SIZE:
                        flush()
                if len(buffer) >= BATCH_SIZE:
                    flush()
            time.sleep(QUERY_PAUSE_SECONDS)

    flush()
    return total_written


def main() -> None:
    """Program entry point: load config, authenticate, collect, and report."""
    config = load_config()
    logger.info(
        "Starting Reddit collection for event=%s window=%s..%s bucket=%s",
        config.event_id,
        config.window_from.isoformat(),
        config.window_to.isoformat(),
        config.target_bucket,
    )
    reddit = praw.Reddit(
        client_id=config.client_id,
        client_secret=config.client_secret,
        user_agent=config.user_agent,
        check_for_async=False,
    )
    reddit.read_only = True
    total = collect(config, reddit)
    logger.info("Reddit collection finished: %d records written.", total)


if __name__ == "__main__":
    main()
