# Phase 1 — Steam collection: 251,639 reviews from launch day

The second source is collected and in BigQuery staging. The dataset is now
two sources, which is what the publisher's cross-source ordering exists to
serve ([ADR 0001](adr/0001-steam-replaces-reddit-as-second-source.md)).

Date: 2026-10-15.

---

## Result

| | |
|---|---|
| Steam reviews in `raw_staging` | **251,639** of 280,699 — **89.6%** |
| Oldest Steam record | **2025-04-24** — launch day |
| Newest Steam record | 2026-10-14 |
| Steam languages present | 47 |
| YouTube comments (unchanged) | 12,254, from 2024-06-09 |
| Total | **263,893 records, two sources** |

## What it took, and why

A single walk does **not** work, and the reason is worth recording because
it is a property of the endpoint, not of the collector.

Steam ends pagination of a result stream long before the data runs out. An
all-languages `filter=recent` walk stopped by itself at page 1243 —
124,187 records — reaching only September 2025 for an April 2025 launch.
The page came back empty; nothing failed, and raising the page cap does
nothing.

A narrower stream holds fewer reviews than that cap, so it reaches the
launch. The collection is therefore **fourteen passes**, and because
review ids are stable, overlap between passes is free: the
`raw_landing` → `raw_staging` MERGE keeps one row per id.

| Pass | Reviews available | Reaches launch |
|---|---|---|
| `review_type=negative`, all languages | 13,409 | yes |
| `english` + `purchase_type=steam` | 103,218 | yes |
| `english` + `purchase_type=non_steam_purchase` | 37,411 | yes |
| `schinese` | 39,575 | yes |
| `french` | 23,607 | yes |
| `russian` | 17,160 | yes |
| `spanish`, `german`, `korean`, `polish`, `tchinese`, `turkish`, `japanese`, `portuguese` | 522–9,971 each | yes |

`english` on its own (140,654) is above the cap, which is why it is split
by purchase type — the last axis the endpoint offers.

Two dead ends, both measured so they are not retried: `day_range` is
clamped to roughly 365 days and cannot reach an 18-month-old launch, and
`filter=updated` is a 400-record stream — a sample of recently edited
reviews, not a route to volume.

The pass set lives in
[`collectors/steam/collect_history.sh`](../collectors/steam/collect_history.sh)
with the count justifying each pass. **That script is the definition of
this dataset**: since the endpoint cannot serve the history in one walk,
"what was collected" is exactly "the union of these streams".

The 9.6% not collected is what no single stream reaches: English reviews
from the capped tail of each partition. Nothing suggests it is biased by
sentiment — negatives are collected exhaustively — but it is not a random
sample either, and the thesis says so rather than claiming completeness.

## Coverage per lifecycle event

Event tags come from each review's own date (nearest event within ±3
days); everything else is `general`.

| event_tag | steam | youtube | thumbs-up share |
|---|---|---|---|
| `xbox_showcase_reveal` | 0 | 1,711 | — |
| `gameplay_trailer_flying_waters` | 0 | 1,257 | — |
| `xbox_developer_direct` | 0 | 292 | — |
| `launch` | 3,915 | 909 | 93.8% |
| `ai_textures_controversy` | 5,742 | 0 | 91.9% |
| `one_million_sales_milestone` | 12,163 | 477 | 92.0% |
| `critical_acclaim_wave` | 13,715 | 351 | **96.2%** |
| `tga_2025_sweep` | 4,749 | 3,328 | **87.6%** |
| `indie_game_awards_rescinded` | 5,075 | 3,502 | 88.0% |
| `anniversary_update_2026` | 895 | 427 | 92.4% |
| `general` | 205,385 | 0 | 95.2% |

Two things to read from this table.

**The sources are complementary, exactly as predicted.** Pre-launch events
are YouTube-only — Steam reviews cannot exist before a game ships — and
from launch onward both sources carry the same moments. The asymmetry is a
property of the sources, reported rather than hidden.

**The weak labels already show the story.** `voted_up` is the author's own
thumbs up/down, not a model output, and it moves: 96.2% positive during
the critical-acclaim wave against 87.6% around the awards sweep and 88.0%
when the Indie Game Awards rescinded them. An 8-point swing in a
self-chosen label is a sanity check no classifier provides — if the model
disagrees with the direction of that movement, the model is wrong.

Also note `general` is 205,385 of the Steam records: most reviews are
written outside a ±3-day event window. Event-window analysis runs on the
~46k tagged Steam records; `general` is the baseline the windows are
compared against.

## What is next, and the one number that decides it

`events` still holds only the 12,254 YouTube rows. Replaying 263,893
records needs the Vertex Endpoint back (deleted after the last replay to
stop the serving bill), and then a throughput decision:

the last Vertex replay classified 12,254 records in ~35 minutes on one
`n1-standard-8` replica. Linearly, 263,893 records is **12 hours** — too
long to be useful.

**Batching is not the lever.** `max_batch_size` defaults to 200 and the
last replay already used it, so those 35 minutes were ~62 predict calls of
200 instances each — about 34 seconds per call, or ~170 ms per review.
That is CPU inference time for XLM-R on an 8-vCPU replica, not call
overhead, so a larger batch moves almost nothing.

What is left is parallelism or less work:

1. **More replicas for the duration of the replay.** Time divides by
   replica count, cost multiplies by it, and the cost is small: an
   `n1-standard-8` replica is roughly $0.38/h, so four replicas for three
   hours is about $5. This is the recommended option — it needs no code
   change, only `min_replica_count` on the deploy, and it is reversible by
   deleting the Endpoint afterwards as before.
2. **Replay the event windows only** (~58k records) and treat `general` as
   a BigQuery-side aggregate rather than a classified stream. Cheaper
   still, but it means `events` no longer holds the whole dataset, which
   costs the "one table, no joins for the dashboard" property.

A GPU replica would beat both on time, but the project deliberately went
CPU-only for serving; four CPU replicas for an afternoon is the smaller
deviation.
