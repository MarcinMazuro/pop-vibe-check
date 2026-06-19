"""Deterministic, salted hashing of author handles.

This module is the GDPR-by-design boundary of the collectors: raw usernames are
turned into a short, irreversible hash here and the original handle must never
leave this layer. The hash is deterministic per ``(username, salt)`` so the same
author always maps to the same ``author_hash`` across the whole dataset.
"""

from __future__ import annotations

import hashlib
import os

_SALT_ENV_VAR = "AUTHOR_HASH_SALT"
_HASH_HEX_LENGTH = 16


def hash_author(username: str, salt: str | None = None) -> str:
    """Hash an author handle into 16 hex characters.

    Computes ``sha256(username + salt)`` and truncates the hex digest to 16
    characters. The result is stable for a given ``(username, salt)`` pair, so a
    given author is identifiable across records without exposing the handle.

    Args:
        username: The raw author handle (Reddit username or YouTube display
            name). Never stored or returned in any output record.
        salt: The project-wide salt. When ``None`` (the default), it is read
            from the ``AUTHOR_HASH_SALT`` environment variable.

    Returns:
        A lowercase, 16-character hexadecimal string.

    Raises:
        ValueError: If no salt is supplied and ``AUTHOR_HASH_SALT`` is unset or
            empty, or if ``username`` is empty. Failing loudly here prevents
            silently writing un-salted (re-identifiable) hashes.
    """
    if not username:
        raise ValueError("Cannot hash an empty username.")

    resolved_salt = salt if salt is not None else os.environ.get(_SALT_ENV_VAR)
    if not resolved_salt:
        raise ValueError(
            f"No salt provided and {_SALT_ENV_VAR} is unset or empty; "
            "refusing to produce an un-salted author hash."
        )

    digest = hashlib.sha256(f"{username}{resolved_salt}".encode()).hexdigest()
    return digest[:_HASH_HEX_LENGTH]
