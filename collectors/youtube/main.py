"""YouTube collector entry point.

Reads a curated list of canonical videos for a lifecycle event, pulls their
comment threads (top-level comments and replies), filters by publish time, and
writes gzipped JSONL batches to the raw archive bucket.

Run as a module::

    python -m collectors.youtube.main

Configuration is taken entirely from environment variables (see the README in
this directory).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from googleapiclient.discovery import build

from collectors.common import build_record, hash_author, resolve_event, write_batch
from collectors.common.retry import retry_transient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("collectors.youtube")

SOURCE = "youtube"
# commentThreads.list costs 1 quota unit; the daily quota is 10,000.
COMMENT_THREADS_PAGE_SIZE = 100
# Records per GCS object.
BATCH_SIZE = 500

_VIDEOS_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "youtube_videos.yaml"
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
        api_key: YouTube Data API v3 key.
    """

    target_bucket: str
    salt: str
    event_id: str
    window_from: datetime
    window_to: datetime
    api_key: str


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
        api_key=_require_env("YOUTUBE_API_KEY"),
    )


def load_videos_for_event(event_id: str, path: Path | None = None) -> list[str]:
    """Return the curated video ids relevant to an event.

    A video is relevant when its ``event_ids`` list contains ``event_id``.
    Placeholder ids (those still flagged with the ``REPLACE`` prefix in the
    config) are skipped with a warning so a half-filled config fails visibly
    rather than calling the API with junk ids.

    Args:
        event_id: The lifecycle event id to filter on.
        path: Optional override for the videos config location.

    Returns:
        The list of YouTube video ids to collect from.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the config is malformed.
    """
    config_path = path if path is not None else _VIDEOS_CONFIG_PATH
    if not config_path.is_file():
        raise FileNotFoundError(f"YouTube videos config not found at {config_path}.")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    entries = raw.get("videos")
    if not isinstance(entries, list):
        raise ValueError(f"{config_path} must contain a top-level 'videos' list.")

    video_ids: list[str] = []
    for entry in entries:
        if event_id not in entry.get("event_ids", []):
            continue
        video_id = str(entry["id"])
        if video_id.startswith("REPLACE"):
            logger.warning(
                "Skipping placeholder video id '%s' (%s) - replace it with a "
                "real YouTube video id in youtube_videos.yaml.",
                video_id,
                entry.get("title", ""),
            )
            continue
        video_ids.append(video_id)
    return video_ids


@retry_transient()
def _execute(request: Any) -> dict[str, Any]:
    """Execute a Google API client request with transient-error retries.

    Args:
        request: A googleapiclient request object.

    Returns:
        The decoded JSON response as a dict.
    """
    result: dict[str, Any] = request.execute()
    return result


def _comment_record(
    snippet: dict[str, Any],
    comment_id: str,
    video_id: str,
    config: RunConfig,
    parent_id: str | None,
) -> dict[str, Any]:
    """Build a record from a YouTube comment snippet.

    Args:
        snippet: The ``snippet`` object of a comment resource.
        comment_id: The YouTube comment id.
        video_id: The id of the video the comment belongs to.
        config: The active run configuration.
        parent_id: Parent comment id for replies, or ``None`` for top-level.

    Returns:
        A collector record dict.
    """
    author = snippet.get("authorDisplayName") or "[deleted]"
    text = snippet.get("textOriginal") or snippet.get("textDisplay") or ""
    return build_record(
        record_id=f"{SOURCE}:{comment_id}",
        source=SOURCE,
        author_hash=hash_author(author, config.salt),
        text=text,
        score=int(snippet.get("likeCount", 0)),
        context_id=video_id,
        event_tag=config.event_id,
        created_utc_epoch=_parse_iso_utc(snippet["publishedAt"]).timestamp(),
        parent_id=parent_id,
    )


def _in_window(snippet: dict[str, Any], config: RunConfig) -> bool:
    """Return whether a comment's publish time falls within the window.

    Args:
        snippet: The comment ``snippet`` containing ``publishedAt``.
        config: The active run configuration.

    Returns:
        ``True`` if ``window_from <= publishedAt < window_to``.
    """
    published = _parse_iso_utc(snippet["publishedAt"])
    return config.window_from <= published < config.window_to


def collect(config: RunConfig, youtube: Any) -> int:
    """Run the collection and write batches to GCS.

    Args:
        config: The active run configuration.
        youtube: A built YouTube Data API v3 client.

    Returns:
        The total number of records written.
    """
    resolve_event(config.event_id)  # Fail loudly on an unknown event id.
    video_ids = load_videos_for_event(config.event_id)
    if not video_ids:
        logger.warning(
            "No curated videos for event '%s'; nothing to do.", config.event_id
        )
        return 0

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

    for video_id in video_ids:
        logger.info("Collecting comments for video %s", video_id)
        page_token: str | None = None
        while True:
            request = youtube.commentThreads().list(
                part="snippet,replies",
                videoId=video_id,
                maxResults=COMMENT_THREADS_PAGE_SIZE,
                order="time",
                textFormat="plainText",
                pageToken=page_token,
            )
            response = _execute(request)

            for thread in response.get("items", []):
                top = thread["snippet"]["topLevelComment"]
                top_snippet = top["snippet"]
                if _in_window(top_snippet, config):
                    buffer.append(
                        _comment_record(
                            top_snippet, top["id"], video_id, config, parent_id=None
                        )
                    )
                for reply in thread.get("replies", {}).get("comments", []):
                    reply_snippet = reply["snippet"]
                    if _in_window(reply_snippet, config):
                        buffer.append(
                            _comment_record(
                                reply_snippet,
                                reply["id"],
                                video_id,
                                config,
                                parent_id=reply_snippet.get("parentId"),
                            )
                        )
                if len(buffer) >= BATCH_SIZE:
                    flush()

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    flush()
    return total_written


def main() -> None:
    """Program entry point: load config, build the client, collect, and report."""
    config = load_config()
    logger.info(
        "Starting YouTube collection for event=%s window=%s..%s bucket=%s",
        config.event_id,
        config.window_from.isoformat(),
        config.window_to.isoformat(),
        config.target_bucket,
    )
    youtube = build("youtube", "v3", developerKey=config.api_key, cache_discovery=False)
    total = collect(config, youtube)
    logger.info("YouTube collection finished: %d records written.", total)


if __name__ == "__main__":
    main()
