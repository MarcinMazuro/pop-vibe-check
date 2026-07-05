"""Exponential-backoff retry helper for transient API errors.

Wraps :mod:`tenacity` to retry on transient HTTP failures (429 and 5xx). PRAW
and the YouTube client both have their own rate-limit handling, so this is used
mainly by the YouTube REST calls and as a general-purpose fallback.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T")

_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _extract_status_code(exc: BaseException) -> int | None:
    """Best-effort extraction of an HTTP status code from an exception.

    Supports the common shapes raised by ``requests``, ``urllib3``, and the
    Google API client (``googleapiclient.errors.HttpError``).

    Args:
        exc: The raised exception.

    Returns:
        The HTTP status code if one can be determined, otherwise ``None``.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status

    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    if isinstance(status, int):
        return status

    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status

    return None


def is_transient_error(exc: BaseException) -> bool:
    """Return whether an exception represents a retryable transient error.

    Args:
        exc: The raised exception.

    Returns:
        ``True`` if the exception carries a 429 or 5xx status code.
    """
    status = _extract_status_code(exc)
    return status in _TRANSIENT_STATUS_CODES


def retry_transient(
    *,
    max_attempts: int = 5,
    initial_wait_seconds: float = 1.0,
    max_wait_seconds: float = 60.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Build a decorator that retries a callable on transient HTTP errors.

    Args:
        max_attempts: Total attempts before giving up (including the first).
        initial_wait_seconds: Base wait for the exponential backoff.
        max_wait_seconds: Upper bound on the backoff wait.

    Returns:
        A decorator applying tenacity retry with exponential backoff, retrying
        only on errors classified as transient by :func:`is_transient_error`.
    """
    return retry(
        retry=retry_if_exception(is_transient_error),
        wait=wait_exponential(multiplier=initial_wait_seconds, max=max_wait_seconds),
        stop=stop_after_attempt(max_attempts),
        reraise=True,
    )
