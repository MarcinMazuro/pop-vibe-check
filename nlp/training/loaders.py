"""Load and mix the hybrid fine-tune corpus.

Hugging Face ``datasets`` is imported inside the loaders that need it so
CI can test label maps without downloading Hub corpora. On Workbench,
point ``cache_dir`` at a local copy of ``gs://co-tf-artifacts-dev/nlp/datasets/``
(see :func:`cache_dir_from_gcs`) so a restarted instance does not hit the
Hub.

The v2 mix (XLM-RoBERTa) is :func:`load_v2_corpus`: clapAI subsample,
multilingual tweets, downsampled tweet_eval / GoEmotions, oversampled
own-domain gold. SST-2 and Sentiment140 stay available behind flags.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Sequence
from pathlib import Path

from nlp.base import normalize_text
from nlp.training.labels import (
    LabeledText,
    map_clapai_label,
    map_goemotions_labels,
    map_sentiment140_label,
    map_sst2_label,
    map_tweet_eval_label,
)

logger = logging.getLogger(__name__)

# Canonical GCS prefix for the Hugging Face datasets cache. Workbench
# rsyncs this to a local disk before `load_dataset`.
DEFAULT_GCS_DATASETS_URI = "gs://co-tf-artifacts-dev/nlp/datasets/"

# tweet_eval sentiment is ~60k across splits; Sentiment140 fills the rest
# in the v1 mix only (off by default for v2).
TWITTER_TARGET = 100_000

CLAPAI_DATASET = "clapAI/MultiLingualSentiment"
CLAPAI_STEAM_LANGS: tuple[str, ...] = ("en", "zh", "ru", "fr", "ko")
CLAPAI_EXTRA_LANGS: tuple[str, ...] = ("de", "es", "ja")
CLAPAI_PER_STEAM_LANG = 18_000
CLAPAI_PER_EXTRA_LANG = 6_000
TWEET_EVAL_TARGET = 25_000
GOEMOTIONS_TARGET = 15_000
OWN_DOMAIN_OVERSAMPLE = 10
MAX_TEXT_CHARS = 512
TWEET_SENTIMENT_ML_CONFIGS: tuple[str, ...] = (
    "arabic",
    "english",
    "french",
    "german",
    "hindi",
    "italian",
    "portuguese",
    "spanish",
)


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
            text = normalize_text(str(row["sentence"]))
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
            text = normalize_text(str(row["text"]))
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
            text = normalize_text(str(row.get("text") or ""))
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
            text = normalize_text(str(row["text"]))
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
    are ignored. Rows with ``split`` equal to ``holdout`` or ``dev`` are
    skipped so they never leak into training — see
    ``nlp/eval/GUIDELINES.md``.

    Args:
        path: JSONL file.

    Returns:
        Mapped examples (text passed through :func:`nlp.base.normalize_text`).

    Raises:
        ValueError: If a row is missing ``text``/``label`` or the label
            is outside the three-class space.
    """
    rows = _load_gold_jsonl(path, skip_splits=frozenset({"holdout", "dev"}))
    logger.info("Loaded %d own-domain examples from %s.", len(rows), path)
    return rows


def load_gold_split(path: str | Path, split: str) -> list[LabeledText]:
    """Load gold JSONL rows whose ``split`` field matches ``split``.

    Unlike :func:`load_own_domain`, this keeps the requested split
    (including ``dev`` and ``holdout``). Used by ``--dev-from-gold``.

    Args:
        path: JSONL file with ``text``, ``label``, and ``split``.
        split: Split name to keep (compared case-insensitively).

    Returns:
        Mapped examples (text passed through :func:`nlp.base.normalize_text`).

    Raises:
        ValueError: If a kept row is missing ``text``/``label`` or the
            label is outside the three-class space.
    """
    wanted = split.strip().lower()
    if not wanted:
        raise ValueError("split must be a non-empty name")
    rows = _load_gold_jsonl(path, keep_split=wanted)
    logger.info("Loaded %d gold %s examples from %s.", len(rows), wanted, path)
    return rows


def _load_gold_jsonl(
    path: str | Path,
    *,
    skip_splits: frozenset[str] | None = None,
    keep_split: str | None = None,
) -> list[LabeledText]:
    """Parse gold JSONL into :class:`LabeledText` rows.

    Args:
        path: JSONL file.
        skip_splits: If set, drop rows whose ``split`` is in this set.
        keep_split: If set, keep only rows whose ``split`` equals this
            name (case-insensitive).

    Returns:
        Mapped examples. Text is passed through :func:`normalize_text`.

    Raises:
        ValueError: On invalid JSON, missing text/label, or (when the
            row is kept) a label outside the three-class space.
    """
    skipped = skip_splits or frozenset()
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
            split = str(payload.get("split") or "").strip().lower()
            if split in skipped:
                continue
            if keep_split is not None and split != keep_split:
                continue
            text = normalize_text(str(payload.get("text") or ""))
            label = str(payload.get("label") or "").strip()
            if not text or not label:
                raise ValueError(
                    f"{path}:{line_no}: both 'text' and 'label' are required"
                )
            source = str(payload.get("source") or "own_domain")
            rows.append(LabeledText(text, label, source))
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


def subsample_rows(
    rows: Sequence[LabeledText],
    n: int,
    *,
    seed: int = 33,
) -> list[LabeledText]:
    """Draw up to ``n`` rows, preserving label proportions.

    Args:
        rows: Mapped examples.
        n: Desired size. ``0`` returns an empty list; ``n >= len(rows)``
            returns a shallow copy.
        seed: RNG seed.

    Returns:
        A new list of length ``min(n, len(rows))``.
    """
    pool = list(rows)
    if n <= 0:
        return []
    if n >= len(pool):
        return pool

    rng = random.Random(seed)
    by_label: dict[str, list[LabeledText]] = {}
    for row in pool:
        by_label.setdefault(row.label, []).append(row)
    for bucket in by_label.values():
        rng.shuffle(bucket)

    chosen: list[LabeledText] = []
    leftover: list[LabeledText] = []
    allocated = 0
    items = list(by_label.items())
    for index, (_label, bucket) in enumerate(items):
        remaining_labels = len(items) - index
        remaining_slots = n - allocated
        if remaining_labels == 1:
            take = min(len(bucket), remaining_slots)
        else:
            take = min(
                len(bucket),
                remaining_slots,
                int(round(n * len(bucket) / len(pool))),
            )
        chosen.extend(bucket[:take])
        leftover.extend(bucket[take:])
        allocated += take

    if len(chosen) < n:
        rng.shuffle(leftover)
        chosen.extend(leftover[: n - len(chosen)])
    rng.shuffle(chosen)
    return chosen[:n]


def oversample_rows(rows: Sequence[LabeledText], factor: int) -> list[LabeledText]:
    """Repeat ``rows`` ``factor`` times.

    Args:
        rows: Mapped examples.
        factor: Repeat count. Values ``<= 1`` return a shallow copy.

    Returns:
        Concatenated copies, original order inside each copy.
    """
    pool = list(rows)
    if factor <= 1:
        return pool
    repeated: list[LabeledText] = []
    for _ in range(factor):
        repeated.extend(pool)
    return repeated


def load_clapai_sample(
    *,
    cache_dir: str | Path | None = None,
    seed: int = 33,
    per_steam_lang: int = CLAPAI_PER_STEAM_LANG,
    per_extra_lang: int = CLAPAI_PER_EXTRA_LANG,
    max_chars: int = MAX_TEXT_CHARS,
) -> list[LabeledText]:
    """Reservoir-sample clapAI MultiLingualSentiment for Steam-centric langs.

    One pass over the train split. Caps are per language and split evenly
    across ``pos`` / ``neu`` / ``neg``. Texts longer than ``max_chars``
    are dropped so the mix matches short game comments.

    Args:
        cache_dir: Hugging Face datasets cache.
        seed: Reservoir RNG seed.
        per_steam_lang: Cap for each of en/zh/ru/fr/ko.
        per_extra_lang: Cap for each of de/es/ja.
        max_chars: Maximum raw text length.

    Returns:
        Mapped examples.
    """
    from datasets import load_dataset

    caps: dict[str, int] = {lang: per_steam_lang for lang in CLAPAI_STEAM_LANGS}
    caps.update({lang: per_extra_lang for lang in CLAPAI_EXTRA_LANGS})
    per_class = {lang: max(1, cap // 3) for lang, cap in caps.items()}
    rng = random.Random(seed)
    buckets: dict[tuple[str, str], list[LabeledText]] = {}
    seen: dict[tuple[str, str], int] = {}

    dataset = load_dataset(CLAPAI_DATASET, cache_dir=_as_cache(cache_dir))
    split = dataset["train"] if "train" in dataset else dataset
    for index, row in enumerate(split):
        if index % 100_000 == 0:
            logger.info("Scanning clapAI train row %d.", index)
        language = str(row.get("language") or "").strip().lower()
        class_cap = per_class.get(language)
        if class_cap is None:
            continue
        raw_text = str(row.get("text") or "").strip()
        if not raw_text or len(raw_text) > max_chars:
            continue
        text = normalize_text(raw_text)
        if not text:
            continue
        try:
            label = map_clapai_label(str(row.get("label") or ""))
        except ValueError:
            continue
        item = LabeledText(text, label, "clapai")
        key = (language, label)
        _reservoir_add(buckets, seen, key, item, class_cap, rng)

    rows = [item for bucket in buckets.values() for item in bucket]
    logger.info(
        "Sampled %d clapAI examples across %d buckets.",
        len(rows),
        len(buckets),
    )
    return rows


def load_tweet_sentiment_multilingual(
    cache_dir: str | Path | None = None,
) -> list[LabeledText]:
    """Load CardiffNLP tweet sentiment in eight languages (all splits).

    Args:
        cache_dir: Hugging Face datasets cache.

    Returns:
        Mapped examples. Configs that fail to load are skipped with a warning.
    """
    from datasets import load_dataset

    rows: list[LabeledText] = []
    cache = _as_cache(cache_dir)
    for config in TWEET_SENTIMENT_ML_CONFIGS:
        try:
            dataset = load_dataset(
                "cardiffnlp/tweet_sentiment_multilingual",
                config,
                cache_dir=cache,
            )
        except Exception as exc:  # noqa: BLE001 — Hub configs vary by revision
            logger.warning("Skipping tweet_sentiment_multilingual/%s: %s", config, exc)
            continue
        for split in dataset:
            for row in dataset[split]:
                text = normalize_text(str(row.get("text") or ""))
                if not text:
                    continue
                try:
                    label = map_tweet_eval_label(int(row["label"]))
                except (ValueError, KeyError, TypeError):
                    continue
                rows.append(LabeledText(text, label, "tweet_sentiment_ml"))
    logger.info("Loaded %d tweet_sentiment_multilingual examples.", len(rows))
    return rows


def load_v2_corpus(
    *,
    cache_dir: str | Path | None = None,
    seed: int = 33,
    own_domain: str | Path | None = None,
    skip_goemotions: bool = False,
    skip_clapai: bool = False,
    skip_tweet_ml: bool = False,
    skip_tweet_eval: bool = False,
    include_sst2: bool = False,
    include_sentiment140: bool = False,
    tweet_eval_target: int = TWEET_EVAL_TARGET,
    goemotions_target: int = GOEMOTIONS_TARGET,
    own_domain_factor: int = OWN_DOMAIN_OVERSAMPLE,
) -> list[LabeledText]:
    """Assemble the multilingual v2 mix (~150–180k examples).

    Args:
        cache_dir: Hugging Face datasets cache.
        seed: Sampling seed.
        own_domain: Optional gold JSONL (holdout and dev rows are skipped).
        skip_goemotions: Drop the Reddit substitute.
        skip_clapai: Drop the clapAI subsample.
        skip_tweet_ml: Drop CardiffNLP multilingual tweets.
        skip_tweet_eval: Drop English tweet_eval.
        include_sst2: Append GLUE SST-2 (v1 leftover; off by default).
        include_sentiment140: Fill Twitter with Sentiment140 (v1 leftover).
        tweet_eval_target: Cap for tweet_eval after downsample.
        goemotions_target: Cap for GoEmotions after downsample.
        own_domain_factor: Repeat count for gold train rows.

    Returns:
        Concatenated mapped examples.
    """
    parts: list[list[LabeledText]] = []
    if not skip_clapai:
        parts.append(load_clapai_sample(cache_dir=cache_dir, seed=seed))
    if not skip_tweet_ml:
        parts.append(load_tweet_sentiment_multilingual(cache_dir=cache_dir))
    if not skip_tweet_eval:
        tweets = load_tweet_eval(cache_dir=cache_dir)
        parts.append(subsample_rows(tweets, tweet_eval_target, seed=seed))
    if include_sentiment140:
        tweet_n = 0 if skip_tweet_eval else tweet_eval_target
        remaining = max(0, TWITTER_TARGET - tweet_n)
        parts.append(
            load_sentiment140_sample(remaining, cache_dir=cache_dir, seed=seed)
        )
    if not skip_goemotions:
        goemotions = load_goemotions(cache_dir=cache_dir)
        parts.append(subsample_rows(goemotions, goemotions_target, seed=seed))
    if include_sst2:
        parts.append(load_sst2(cache_dir=cache_dir))
    if own_domain:
        gold = load_own_domain(own_domain)
        parts.append(oversample_rows(gold, own_domain_factor))
    mixed = mix_corpus(parts)
    logger.info("v2 corpus: %d examples.", len(mixed))
    return mixed


def _reservoir_add(
    buckets: dict[tuple[str, str], list[LabeledText]],
    seen: dict[tuple[str, str], int],
    key: tuple[str, str],
    item: LabeledText,
    cap: int,
    rng: random.Random,
) -> None:
    """Algorithm R: keep at most ``cap`` items per ``key``.

    Args:
        buckets: Reservoirs keyed by (language, label).
        seen: How many candidates have been offered for each key.
        key: Bucket identity.
        item: Candidate example.
        cap: Maximum bucket size.
        rng: Seeded RNG.
    """
    seen[key] = seen.get(key, 0) + 1
    count = seen[key]
    bucket = buckets.setdefault(key, [])
    if len(bucket) < cap:
        bucket.append(item)
        return
    replace_at = rng.randrange(count)
    if replace_at < cap:
        bucket[replace_at] = item


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
