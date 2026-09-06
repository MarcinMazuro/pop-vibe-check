"""Load and mix the hybrid fine-tune corpus.

Hugging Face ``datasets`` is imported inside the loaders that need it so
CI can test label maps without downloading SST-2 or Twitter. On Workbench,
point ``cache_dir`` at a local copy of ``gs://co-tf-artifacts-dev/nlp/datasets/``
(see :func:`cache_dir_from_gcs`) so a restarted instance does not hit the
Hub.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Sequence
from pathlib import Path

from nlp.training.labels import (
    LabeledText,
    map_goemotions_labels,
    map_sentiment140_label,
    map_sst2_label,
    map_tweet_eval_label,
)

logger = logging.getLogger(__name__)

# Canonical GCS prefix for the Hugging Face datasets cache. Workbench
# rsyncs this to a local disk before `load_dataset`.
DEFAULT_GCS_DATASETS_URI = "gs://co-tf-artifacts-dev/nlp/datasets/"

# tweet_eval sentiment is ~60k across splits; Sentiment140 fills the rest.
TWITTER_TARGET = 100_000


def cache_dir_from_gcs(
    gcs_uri: str = DEFAULT_GCS_DATASETS_URI,
    local_dir: str | Path = "/tmp/hf-datasets",
) -> Path:
    """Rsync a GCS dataset cache to a local directory.

    Hugging Face ``load_dataset`` does not read ``gs://`` as ``cache_dir``
    directly. Workbench therefore copies the prefix once per session.

    Args:
        gcs_uri: GCS prefix populated by a previous download+upload.
        local_dir: Local destination.

    Returns:
        The local cache path (created if missing).

    Raises:
        RuntimeError: If ``gsutil`` fails. Callers that already have a
            warm local cache can skip this function and pass ``cache_dir``
            straight to the loaders.
    """
    import shutil
    import subprocess

    destination = Path(local_dir)
    destination.mkdir(parents=True, exist_ok=True)
    gsutil = shutil.which("gsutil")
    if gsutil is None:
        logger.warning("gsutil not on PATH; using empty cache at %s", destination)
        return destination
    result = subprocess.run(
        [gsutil, "-m", "rsync", "-r", gcs_uri, str(destination)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gsutil rsync from {gcs_uri} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return destination


def load_sst2(cache_dir: str | Path | None = None) -> list[LabeledText]:
    """Load GLUE SST-2 (train + validation) mapped to ``pos`` / ``neg``.

    Args:
        cache_dir: Hugging Face datasets cache. ``None`` uses the library
            default (which hits the Hub if the split is not cached).

    Returns:
        Mapped examples. Neutral is absent by construction.
    """
    from datasets import load_dataset

    dataset = load_dataset("glue", "sst2", cache_dir=_as_cache(cache_dir))
    rows: list[LabeledText] = []
    for split in ("train", "validation"):
        for row in dataset[split]:
            text = str(row["sentence"]).strip()
            if not text:
                continue
            rows.append(LabeledText(text, map_sst2_label(int(row["label"])), "sst2"))
    logger.info("Loaded %d SST-2 examples.", len(rows))
    return rows


def load_tweet_eval(cache_dir: str | Path | None = None) -> list[LabeledText]:
    """Load ``tweet_eval`` sentiment (all splits), three-class.

    Args:
        cache_dir: Hugging Face datasets cache.

    Returns:
        Mapped examples.
    """
    from datasets import load_dataset

    dataset = load_dataset("tweet_eval", "sentiment", cache_dir=_as_cache(cache_dir))
    rows: list[LabeledText] = []
    for split in dataset:
        for row in dataset[split]:
            text = str(row["text"]).strip()
            if not text:
                continue
            rows.append(
                LabeledText(
                    text,
                    map_tweet_eval_label(int(row["label"])),
                    "tweet_eval",
                )
            )
    logger.info("Loaded %d tweet_eval examples.", len(rows))
    return rows


def load_sentiment140_sample(
    n: int,
    *,
    cache_dir: str | Path | None = None,
    seed: int = 33,
) -> list[LabeledText]:
    """Draw ``n`` Sentiment140 rows, mapped onto ``pos`` / ``neu`` / ``neg``.

    Args:
        n: Sample size. ``0`` returns an empty list.
        cache_dir: Hugging Face datasets cache.
        seed: RNG seed so two Workbench sessions draw the same supplement.

    Returns:
        Mapped examples, at most ``n`` long. Skips rows whose polarity
        cannot be mapped.
    """
    if n <= 0:
        return []

    from datasets import load_dataset

    dataset = load_dataset("stanfordnlp/sentiment140", cache_dir=_as_cache(cache_dir))
    pool: list[LabeledText] = []
    for split in dataset:
        for row in dataset[split]:
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            try:
                label = map_sentiment140_label(int(row["sentiment"]))
            except (ValueError, KeyError, TypeError):
                continue
            pool.append(LabeledText(text, label, "sentiment140"))
    rng = random.Random(seed)
    if n >= len(pool):
        chosen = pool
    else:
        chosen = rng.sample(pool, n)
    logger.info("Sampled %d / %d Sentiment140 examples.", len(chosen), len(pool))
    return chosen


def load_twitter(
    *,
    target: int = TWITTER_TARGET,
    cache_dir: str | Path | None = None,
    seed: int = 33,
) -> list[LabeledText]:
    """Combine tweet_eval with a Sentiment140 sample to reach ``target``.

    Args:
        target: Desired Twitter-side size (~100k).
        cache_dir: Hugging Face datasets cache.
        seed: Passed through to the Sentiment140 sample.

    Returns:
        tweet_eval rows plus however many Sentiment140 rows are needed
        to approach ``target``. If tweet_eval alone exceeds ``target``,
        it is returned in full — we do not discard 3-class in-domain
        tweets to make room for binary Sentiment140.
    """
    tweets = load_tweet_eval(cache_dir=cache_dir)
    remaining = max(0, target - len(tweets))
    extra = load_sentiment140_sample(remaining, cache_dir=cache_dir, seed=seed)
    combined = tweets + extra
    logger.info("Twitter mix: %d rows (target %d).", len(combined), target)
    return combined


def load_goemotions(cache_dir: str | Path | None = None) -> list[LabeledText]:
    """Load GoEmotions as a Reddit-comment substitute (open access).

    The project Reddit collector has no credentials. This public,
    labelled Reddit set closes that gap for fine-tuning; the collector
    in this repo is unchanged.

    Args:
        cache_dir: Hugging Face datasets cache.

    Returns:
        Mapped examples. Empty-text rows are dropped.
    """
    from datasets import load_dataset

    dataset = load_dataset("go_emotions", "simplified", cache_dir=_as_cache(cache_dir))
    names: list[str] = list(dataset["train"].features["labels"].feature.names)
    rows: list[LabeledText] = []
    for split in dataset:
        for row in dataset[split]:
            text = str(row["text"]).strip()
            if not text:
                continue
            emotions = [names[int(i)] for i in row["labels"]]
            rows.append(
                LabeledText(text, map_goemotions_labels(emotions), "goemotions")
            )
    logger.info("Loaded %d GoEmotions examples.", len(rows))
    return rows


def load_own_domain(path: str | Path) -> list[LabeledText]:
    """Load hand-labelled own-domain notes (YouTube gold / JSONL).

    Each line is a JSON object with ``text`` and ``label`` (``pos`` /
    ``neu`` / ``neg``). Extra fields (``id``, ``language``, ``source``)
    are ignored. This is the hold-in / hold-out split from the ~300 gold
    sample — see ``nlp/eval/GUIDELINES.md``.

    Args:
        path: JSONL file.

    Returns:
        Mapped examples.

    Raises:
        ValueError: If a row is missing ``text``/``label`` or the label
            is outside the three-class space.
    """
    rows: list[LabeledText] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON") from exc
            text = str(payload.get("text") or "").strip()
            label = str(payload.get("label") or "").strip()
            if not text or not label:
                raise ValueError(
                    f"{path}:{line_no}: both 'text' and 'label' are required"
                )
            source = str(payload.get("source") or "own_domain")
            rows.append(LabeledText(text, label, source))
    logger.info("Loaded %d own-domain examples from %s.", len(rows), path)
    return rows


def mix_corpus(
    parts: Sequence[Sequence[LabeledText]],
) -> list[LabeledText]:
    """Concatenate dataset parts, dropping empty texts.

    Args:
        parts: Already-mapped splits (SST-2, Twitter, own-domain, …).

    Returns:
        A single list. Order is preserved so a seeded shuffle later is
        reproducible.
    """
    mixed: list[LabeledText] = []
    for part in parts:
        mixed.extend(row for row in part if row.text.strip())
    return mixed


def _as_cache(cache_dir: str | Path | None) -> str | None:
    """Return ``cache_dir`` as a string, or ``None``.

    Args:
        cache_dir: Optional path.

    Returns:
        The path as ``str``, or ``None`` if unset.
    """
    if cache_dir is None:
        return None
    return str(cache_dir)
