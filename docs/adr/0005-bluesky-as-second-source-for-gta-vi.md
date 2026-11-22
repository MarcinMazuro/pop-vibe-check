# ADR 0005 — Bluesky as the second source for GTA VI

- **Status:** Accepted
- **Date:** 2026-11-22
- **Extends:** [ADR 0001](0001-steam-replaces-reddit-as-second-source.md),
  whose source (Steam) does not exist for this release
- **Affects:** `collectors/`, the `events` table's `source` domain,
  Secret Manager (a new credential), the live-collection plan in
  `docs/phase-3-plan.md`

## Context

The second case study is *Grand Theft Auto VI*, released 2026-11-19 on
PS5 and Xbox Series X|S only. There is no PC version and so no Steam
page: no appid, no reviews, nothing for `collectors/steam/` to read. A PC
release is reported, unofficially, for early 2027.

ADR 0001's reasoning still holds: with a single source, the cross-source
ordering guarantee the publisher exists for is never exercised. GTA VI
needs a second source of its own.

The release is also the project's live-collection case: its launch is
days old, so the source must serve recent data on a short cadence as well
as history.

## Decision

**Public Bluesky posts, found through `app.bsky.feed.searchPosts`, are
the second source for GTA VI.** The collector is `collectors/bluesky/`.
It is release-agnostic and can serve any release; the queries are a
deployment setting.

Search takes `since` and `until`, so one code path serves both modes: a
long window cut into slices for history, a short look-back window on a
schedule for live collection.

### Why Bluesky rather than another substitute

Candidates looked at on 2026-11-22:

| Candidate | Verdict |
|---|---|
| **Bluesky** | Official, documented API; free; time-windowed search; post volume confirmed (below) |
| Microsoft Store (Xbox) reviews | Rejected: reachable only through an undocumented endpoint with no terms to rely on |
| Metacritic user reviews | Rejected: no public API, and scraping runs against the site's terms |
| Twitch chat | Rejected: no history at all, and short chat lines carry little sentiment |

A volume probe found a full first page (100 posts) in every hour sampled:
two days after launch, the second trailer (2025-05-06), and the first
trailer (2023-12-05) — the last while Bluesky was still invite-only, so
pre-launch coverage is thinner but present.

## Consequences

- **A credential, unlike Steam.** Search refuses anonymous pagination
  (the first page answers, later pages return 403), so the collector logs
  in with an **app password** — revocable on its own, with no account
  management rights — stored in the `bluesky-app-password` secret. The
  handle is not secret and is a Terraform variable. One session per run:
  the PDS rate-limits logins to a few hundred a day.
- **Privacy is unchanged and non-negotiable.** The author's DID is hashed
  like every other author identifier; handle, display name and avatar are
  never written. Because a post's AT URI embeds the DID, the record `id`
  and `parent_id` are salted hashes of the whole URI. They do **not** embed
  the author hash either: `id` is exposed by the reporting layer, and it
  must not let a reader group posts by author. Threads stay reconstructible
  because a reply's `parent_id` is computed from the parent's URI.
- **`created_utc` is the earlier of `createdAt` and `indexedAt`.** The
  first is set by the author's client and can claim any date; search
  filters on the same axis, so a post sits where search placed it.
- **Search depth is finite.** A long window is read as slices
  (`BLUESKY_SLICE_MINUTES`) with a per-slice page cap; hitting the cap is
  logged, never silent, and the fix is narrower slices for that period.
- **`source` takes the value `bluesky`; `context_id` holds the query**
  that found the post, the nearest analogue of a video id. A post found
  by several queries is written once. `voted_up` stays NULL.
- **Sample bias is a finding, not a defect.** Bluesky's user base is not
  the gaming public at large; the analysis reports the source mix rather
  than presenting one platform as "the internet".
- **The job is opt-in per composition** (`enable_bluesky`), because Cloud
  Run validates secret references when it creates a job and an empty
  secret would fail the apply.
- The supervisor is told, as with ADR 0001.

## Alternatives considered

- **YouTube only for GTA VI.** Leaves the ordering design unexercised for
  the release that most needs it — live data from two clocks.
- **Wait for the PC release and use Steam.** Misses the launch entirely,
  which is the period live collection exists for.
- **The Jetstream firehose for live data.** No login needed, but it is
  every post on the network, filtered client-side by a process that never
  stops — a running service, not a scheduled job. Search on a short
  window gives the same records with the existing job shape.
