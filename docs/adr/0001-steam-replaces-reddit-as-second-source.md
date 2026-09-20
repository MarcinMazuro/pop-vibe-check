# ADR 0001 — Steam reviews replace Reddit as the second data source

- **Status:** Accepted
- **Date:** 2026-09-20
- **Supersedes:** the Reddit half of the original two-source design
- **Affects:** `collectors/`, the `events` table's `source` domain, the
  multi-source ordering argument the publisher exists to serve

## Context

The system was designed around two sources: Reddit and YouTube. Reddit
API access was requested and refused, with no workaround available, so
that half of the collection design cannot be built. `collectors/reddit/`
stays in the repository, complete and unused, as evidence of what was
written before access was refused.

Dropping to a single source costs more than a row count. Global
chronological ordering **across sources** is a binding decision, and it
is the reason the publisher exists at all: Pub/Sub cannot guarantee
global order, so the archive is sorted in BigQuery (`ORDER BY
created_utc, source, id`) and streamed out under ordering keys. With one
source, that design still runs but nothing exercises it — the thesis
would argue for a mechanism it never demonstrates.

## Decision

**Steam reviews for *Clair Obscur: Expedition 33* (appid `1903340`)
become the second source.** Further sources may be added later if one
proves accessible; the collection design already treats sources as
interchangeable, so adding a third is additive rather than structural.

The store review endpoint
(`store.steampowered.com/appreviews/<appid>?json=1`) returns JSON over
plain HTTPS with no authentication, no registration and no quota
application — there is no approval process that can refuse us. Checked
2026-09-05: 277,523 reviews, cursor pagination at 100 per page,
`filter=recent` in strictly descending `timestamp_created`.

### Why Steam rather than another substitute

- **It restores the multi-source argument.** Two sources with genuinely
  different clocks put the ordering guarantee back under test.
- **The schema is unchanged.** `recommendationid` → `id` (prefixed
  `steam:`), `timestamp_created` → `created_utc`, `review` → `text`,
  `votes_up` → `score`, appid → `context_id`, `parent_id` null (reviews
  are flat). No migration of the `events` table.
- **It is complementary, not redundant.** The game launched 2025-04-24,
  so Steam starts at launch and goes deep; YouTube covers the full cycle
  including reveal and trailers. The gap between their coverage is itself
  worth analysing.
- **It supplies weak ground truth.** Every review carries `voted_up`, an
  author-chosen thumbs up/down — a free label to validate the sentiment
  classifier at scale, alongside the hand-labelled gold set.
- **It is multilingual.** A sample page ran 49% English, the rest mostly
  Chinese, Russian, French and Korean — an input to the model decision,
  not a footnote.

## Consequences

- A `collectors/steam/` service is built to the pattern of
  `collectors/youtube/`, reusing `collectors/common/` for hashing,
  retries and the GCS writer.
- `source` takes the value `steam`. Anything enumerating sources
  (dashboards, event tagging, per-source aggregates) must include it.
- **Privacy is unchanged and non-negotiable.** Only the salted, truncated
  SHA-256 of `author.steamid` leaves the collector;
  `author.personaname` and `author.profile_url` are never written to GCS.
  Steam profile identifiers are personal data on the same footing as
  YouTube handles.
- The endpoint is public but undocumented: back off politely (the shared
  retry helper already does), and identify the client honestly in the
  user agent.
- Pre-launch events keep YouTube-only coverage. That asymmetry is
  reported in the analysis rather than hidden.
- The thesis text names Steam, not Reddit, as the second source, and
  documents the refusal as a real-world constraint on the project.

## Alternatives considered

- **Single source (YouTube only).** Cheapest, but leaves the ordering
  design unexercised and the multi-source claim unsupported.
- **X / Twitter.** Out of scope since 2023 — the free tier cannot support
  collection at this volume.
- **Unofficial Reddit scraping.** Rejected: it violates the platform's
  terms, and a thesis result that cannot be regenerated lawfully is not a
  result.
