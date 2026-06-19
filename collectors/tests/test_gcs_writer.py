"""Tests for the GCS writer serialisation and path/upload behaviour."""

from __future__ import annotations

import gzip
import json
import re

import pytest

from collectors.common import gcs_writer


def test_serialise_produces_one_json_object_per_line():
    records = [{"id": "a", "score": 1}, {"id": "b", "score": 2}]
    payload = gcs_writer.serialise_jsonl_gz(records)
    text = gzip.decompress(payload).decode("utf-8")

    lines = text.split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"id": "a", "score": 1}
    assert json.loads(lines[1]) == {"id": "b", "score": 2}


def test_serialise_is_compact_without_trailing_newline():
    payload = gcs_writer.serialise_jsonl_gz([{"id": "a"}])
    text = gzip.decompress(payload).decode("utf-8")
    assert text == '{"id":"a"}'


def test_object_path_matches_partition_convention():
    path = gcs_writer.build_object_path("reddit", "launch", "deadbeef")
    assert re.fullmatch(
        r"reddit/launch/\d{4}/\d{2}/\d{2}/\d{2}/deadbeef\.jsonl\.gz", path
    )


class _FakeBlob:
    def __init__(self) -> None:
        self.payload: bytes | None = None
        self.content_type: str | None = None

    def upload_from_string(self, data: bytes, content_type: str) -> None:
        self.payload = data
        self.content_type = content_type


class _FakeBucket:
    def __init__(self) -> None:
        self.blob_obj = _FakeBlob()
        self.requested_path: str | None = None

    def blob(self, path: str) -> _FakeBlob:
        self.requested_path = path
        return self.blob_obj


class _FakeClient:
    def __init__(self) -> None:
        self.bucket_obj = _FakeBucket()
        self.requested_bucket: str | None = None

    def bucket(self, name: str) -> _FakeBucket:
        self.requested_bucket = name
        return self.bucket_obj


def test_write_batch_uploads_and_returns_uri():
    client = _FakeClient()
    records = [{"id": "reddit:t3_x", "text": "hi"}]

    uri = gcs_writer.write_batch(
        records, "reddit", "launch", bucket="co-raw-archive-dev", client=client
    )

    assert client.requested_bucket == "co-raw-archive-dev"
    assert uri.startswith("gs://co-raw-archive-dev/reddit/launch/")
    blob = client.bucket_obj.blob_obj
    assert blob.content_type == "application/gzip"
    assert blob.payload is not None
    decoded = gzip.decompress(blob.payload).decode("utf-8")
    assert json.loads(decoded) == {"id": "reddit:t3_x", "text": "hi"}


def test_write_batch_empty_is_noop_but_returns_uri():
    client = _FakeClient()
    uri = gcs_writer.write_batch([], "youtube", "launch", bucket="b", client=client)
    assert uri.startswith("gs://b/youtube/launch/")
    assert client.bucket_obj.blob_obj.payload is None


def test_write_batch_requires_bucket(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TARGET_BUCKET", raising=False)
    with pytest.raises(ValueError):
        gcs_writer.write_batch([{"id": "a"}], "reddit", "launch", client=_FakeClient())
