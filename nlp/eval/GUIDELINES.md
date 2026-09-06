# Gold-set annotation guidelines

Hand-label ~300 comments/reviews for DistilBERT evaluation. Labels must
match the pipeline's three classes: `pos`, `neu`, `neg`.

## What you are labelling

The **author's sentiment toward the game / the event**, not toward
another commenter, and not factual correctness.

The unit is one row from `raw_staging` (YouTube comment, later Reddit or
Steam review). Read `text` in isolation first; `event_tag` and `source`
are tie-breakers only.

## Labels

| Label | Use when |
|---|---|
| `pos` | Praise, excitement, recommendation, celebration of the game or event. |
| `neg` | Complaint, disappointment, refund talk, mockery of the game or event. |
| `neu` | Mixed in equal measure, purely informational, off-topic, or too short to tell. |

## Decision rules

1. **Mixed.** If both praise and complaint are present, pick the polarity
   that dominates the text. A true 50/50 split is `neu`.
2. **Sarcasm.** Label the implied polarity ("yeah, amazing 10/10 crash")
   is `neg`.
3. **Questions.** "When does it come out?" is `neu`. "Why is this so
   broken?" is `neg`.
4. **Non-English.** Still label. DistilBERT-base-uncased is English; the
   eval report slices by `language` so FR/ZH/RU/KO rows measure the
   documented limit, they are not a quality promise.
5. **Empty / emoji-only.** `neu`, unless the emoji is unambiguously
   polarised (🔥❤️ vs 💩).
6. **Spoilers, memes, @replies.** If they express a stance on the game,
   label that stance; otherwise `neu`.
7. **Do not** invent a fourth class. Do not skip a row. Unsure → `neu`.

## Hold-out vs fine-tune

From the ~300, keep a **hold-out of at least 80 rows** that never enter
`nlp/training` `--own-domain`. The rest may be appended to the hybrid
corpus. Record the split in the gold JSONL (`split: train|holdout`).

## File format

JSONL, one object per line:

```json
{"id": "youtube:Ugx…", "text": "…", "source": "youtube", "language": "en", "event_tag": "launch", "label": "pos", "split": "holdout"}
```

See `sample_gold.py` and `sql/sample_gold.sql` for how to draw the sample.
