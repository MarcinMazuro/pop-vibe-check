"""Tests for the release config directory resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from collectors.common.release_config import known_releases, release_config_dir


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    (tmp_path / "clair_obscur").mkdir()
    (tmp_path / "gta6").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "stray.yaml").write_text("x: 1\n")
    return tmp_path


def test_known_releases_lists_directories_only(root):
    assert known_releases(root) == ["clair_obscur", "gta6"]


def test_explicit_release_wins_over_env(root, monkeypatch):
    monkeypatch.setenv("RELEASE", "clair_obscur")
    assert release_config_dir("gta6", root) == root / "gta6"


def test_release_read_from_env(root, monkeypatch):
    monkeypatch.setenv("RELEASE", " gta6 ")
    assert release_config_dir(root=root) == root / "gta6"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_release_fails_loudly(root, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("RELEASE", raising=False)
    else:
        monkeypatch.setenv("RELEASE", value)
    with pytest.raises(ValueError, match="RELEASE is unset"):
        release_config_dir(root=root)


def test_unknown_release_names_the_known_ones(root):
    with pytest.raises(ValueError, match="Known releases: clair_obscur, gta6"):
        release_config_dir("witcher4", root)


@pytest.mark.parametrize("name", ["../etc", "GTA6", "gta-6", "_private"])
def test_malformed_release_rejected(root, name):
    with pytest.raises(ValueError, match="Malformed"):
        release_config_dir(name, root)


def test_repository_has_clair_obscur():
    assert "clair_obscur" in known_releases()
