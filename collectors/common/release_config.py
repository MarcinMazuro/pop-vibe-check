"""Locate the configuration directory of the release being studied.

Every release has its own directory under ``collectors/config/`` holding
its ``events.yaml`` (lifecycle events, used for tagging) and its
``youtube_videos.yaml`` (curated videos). All directories are baked into
every image; the ``RELEASE`` environment variable picks one at run time.

``RELEASE`` is required and has no default on purpose. A job for one game
that silently fell back to another game's config would tag records with
the wrong lifecycle events and write them under the wrong archive
prefixes, and nothing downstream would notice.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

CONFIG_ROOT = Path(__file__).resolve().parent.parent / "config"
RELEASE_ENV_VAR = "RELEASE"

_RELEASE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")


def known_releases(root: Path | None = None) -> list[str]:
    """Return the releases that have a config directory, sorted.

    Args:
        root: Optional override for the config root directory.

    Returns:
        Directory names under the config root.
    """
    base = root if root is not None else CONFIG_ROOT
    if not base.is_dir():
        return []
    return sorted(
        p.name
        for p in base.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    )


def release_config_dir(release: str | None = None, root: Path | None = None) -> Path:
    """Resolve the config directory for a release.

    Args:
        release: Release name (e.g. ``"clair_obscur"``). Read from the
            ``RELEASE`` environment variable when omitted.
        root: Optional override for the config root directory.

    Returns:
        The path of the release's config directory.

    Raises:
        ValueError: If no release is given, the name is malformed, or the
            release has no config directory.
    """
    name = release if release is not None else os.environ.get(RELEASE_ENV_VAR, "")
    name = name.strip()
    base = root if root is not None else CONFIG_ROOT
    known = ", ".join(known_releases(base)) or "<none>"

    if not name:
        raise ValueError(
            f"Required environment variable {RELEASE_ENV_VAR} is unset or empty. "
            f"Known releases: {known}."
        )
    if not _RELEASE_PATTERN.match(name):
        raise ValueError(
            f"Malformed release name '{name}': use lowercase letters, digits "
            "and underscores."
        )

    directory = base / name
    if not directory.is_dir():
        raise ValueError(f"Unknown release '{name}'. Known releases: {known}.")
    return directory
