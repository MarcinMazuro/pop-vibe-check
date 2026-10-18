# Phase 1 — the full two-source replay

Both sources, the real model, the whole dataset: 263,893 records
classified by XLM-R v2.1 and promoted into `events`. This is the run the
thesis numbers come from.

Date: 2026-10-18. Commit: `f88c3c9`. Build: `945922cf`.

---

## Result

| | |
|---|---|
| Records replayed | **263,893** — 251,639 Steam + 12,254 YouTube |
| Rows in `events` | 263,893 — one per `id` |
| Missing ids (coverage check) | 0 |
| Rows without sentiment | 0 |
| `model_version` values | **1** — `xlmr-sent-v2.1` |
| Reproducibility fingerprint | `1362546813658964988819` |
| Wall clock | ~2h30m |

Serving ran on two replicas of the same checkpoint — `n2-standard-8` plus
`n2d-standard-8`, 50% traffic each — because Vertex counts serving CPUs
per machine family and the N1 pool was stuck. Both replicas were
undeployed when the run drained; an empty Endpoint does not bill.

## The model against the authors' own verdict

Every Steam review carries `voted_up`, a thumbs up or down the author
chose. The model never sees it. On the 210,009 reviews where the model
committed to a polarity rather than `neu`:

**95.3% agreement.**

| author said | reviews | model `pos` | model `neu` | model `neg` |
|---|---|---|---|---|
| 👍 thumbs up | 238,212 | **80.7%** | 16.0% | 3.3% |
| 👎 thumbs down | 13,427 | 15.4% | 27.0% | **57.6%** |

The asymmetry is the interesting part. A thumbs-up review is called
positive 24 times more often than negative; a thumbs-down review is
called negative only 3.7 times more often than positive, and a quarter of
them land in `neu`. Negative reviews of a game people broadly like are
mixed, sarcastic and conditional — "great game, terrible port" — which is
exactly the text a three-class classifier struggles to commit on. The
hand-labelled gold set reports accuracy 0.746; this says the same thing
at a thousand times the scale and for free.

## Sentiment across the lifecycle

| event | records | model net | authors' thumbs (Steam) |
|---|---|---|---|
| `xbox_showcase_reveal` | 1,711 | 0.556 | — |
| `gameplay_trailer_flying_waters` | 1,257 | 0.457 | — |
| `xbox_developer_direct` | 292 | 0.596 | — |
| `launch` | 4,824 | 0.636 | 0.938 |
| `ai_textures_controversy` | 5,742 | 0.679 | 0.919 |
| `one_million_sales_milestone` | 12,640 | 0.669 | 0.920 |
| `critical_acclaim_wave` | 14,066 | **0.730** | **0.962** |
| `tga_2025_sweep` | 8,077 | 0.535 | 0.876 |
| `indie_game_awards_rescinded` | 8,577 | **0.316** | 0.880 |
| `anniversary_update_2026` | 1,322 | 0.649 | 0.924 |
| `general` | 205,385 | 0.716 | 0.952 |

`net` is (positive − negative) / total, in [−1, 1]. The two columns move
together — peak at the critical-acclaim wave, trough around the awards —
which is the validation that matters: an independent signal the model
cannot see agrees with its direction.

## The two sources disagree, and that is the finding

The model's trough at `indie_game_awards_rescinded` (0.316) is far deeper
than the authors' thumbs (0.880) suggest. Splitting by source explains
it:

| event | Steam net | YouTube net |
|---|---|---|
| `launch` | 0.685 | 0.425 |
| `critical_acclaim_wave` | 0.742 | 0.254 |
| `tga_2025_sweep` | 0.619 | 0.415 |
| `indie_game_awards_rescinded` | **0.608** | **−0.108** |

Steam stays positive through the controversy. YouTube goes **negative** —
the only negative reading anywhere in the dataset. Overall: Steam 77.2%
positive against YouTube 48.4%, with 6.2% versus 18.7% negative.

Two platforms, the same release, the same week, opposite verdicts. A
Steam review is written by someone who bought and played the game; a
YouTube comment under an awards-controversy video is written by anyone
with an opinion about the controversy. Single-source sentiment analysis
would have reported whichever of these two stories it happened to
collect — which is the argument for two sources made with data rather
than with design intent.

## What this run cost

Two serving replicas for the duration (~$4), four Dataflow workers
(~$1), BigQuery and Pub/Sub below a zloty. The expensive mistake was not
the compute: it was replaying 263,893 records twice because the publisher
dropped a column, and a third time because a template parameter was not
declared. Both now have tests.
