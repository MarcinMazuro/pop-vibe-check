"""Tests for the author hashing GDPR boundary."""

from __future__ import annotations

import pytest

from collectors.common.author_hash import hash_author


def test_hash_is_deterministic_for_same_username_and_salt():
    assert hash_author("alice", "pepper") == hash_author("alice", "pepper")


def test_hash_is_16_hex_chars():
    digest = hash_author("alice", "pepper")
    assert len(digest) == 16
    assert all(c in "0123456789abcdef" for c in digest)


def test_hash_is_salt_sensitive():
    assert hash_author("alice", "pepper") != hash_author("alice", "other-salt")


def test_hash_differs_per_username():
    assert hash_author("alice", "pepper") != hash_author("bob", "pepper")


def test_salt_read_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTHOR_HASH_SALT", "env-salt")
    assert hash_author("alice") == hash_author("alice", "env-salt")


def test_missing_salt_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AUTHOR_HASH_SALT", raising=False)
    with pytest.raises(ValueError):
        hash_author("alice")


def test_empty_username_raises():
    with pytest.raises(ValueError):
        hash_author("", "pepper")
