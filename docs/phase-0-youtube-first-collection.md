# Phase 0 — YouTube collector: deployment and first real collection

Follow-up to [phase-0-collectors.md](phase-0-collectors.md). This document
records the completion of the YouTube half of the collector follow-up list:
real video ids, a working API key, the image build, and the first four
production collection runs. The Reddit collector is untouched — it still
waits for Reddit API credentials.

Date: 2026-07-05.

---

## What was done

### 1. Curated video list populated (`collectors/config/youtube_videos.yaml`)

The `REPLACE` placeholders were swapped for 9 real videos, each verified via
the YouTube Data API (`videos.list`: channel, publish date, comment count)
before being committed:

| Video id | Channel | Published | Event(s) |
|---|---|---|---|
| `IDyqGZy78Ng` | XBOX | 2024-06-09 | `xbox_showcase_reveal` |
| `Sq1RTsJ9DN8` | GameSpot | 2024-06-09 | `xbox_showcase_reveal` |
| `-qgOZDRDynw` | PlayStation | 2024-06-10 | `xbox_showcase_reveal` |
| `Gr0Z-K89k6k` | PlayStation | 2024-08-28 | `gameplay_trailer_flying_waters` |
| `YJnjReKXrvk` | GameSpot Trailers | 2024-08-28 | `gameplay_trailer_flying_waters` |
| `2VaLOc1FpSo` | PlayStation | 2025-04-24 | `launch` |
| `oecZmlLXqXk` | BANDAI NAMCO Europe | 2025-04-24 | `launch` |
| `KvJv-Rlx4bI` | IGN | 2025-04-23 | `launch`, `critical_acclaim_wave` |
| `D29V8pRV4oY` | GameSpot | 2025-06-02 | `critical_acclaim_wave` |

`ai_textures_controversy` keeps its placeholder: API search over the
2025-04-24..06-15 window surfaced no dedicated "AI textures" video from the
launch period. YouTube coverage of the AI-usage topic clusters around the
December 2025 TGA controversy instead (e.g. SamDoesArts `y8jhntgQgf0`,
2025-12-27). Either find a contemporaneous video manually or retarget the
event at the December wave.

### 2. YouTube API key fixed

The value stored in `co-youtube-api-key-dev` (version 1, added 2026-05-23)
was **not a valid key** — 28 characters, rejected by the API with
`API_KEY_INVALID` (real Google API keys are 39 chars, `AIza...`). Fix:

- Created a new API key via `gcloud services api-keys create`, restricted to
  `youtube.googleapis.com` only
  (key resource: `.../keys/fb84c91b-53ed-4345-9eed-2d735f111e67`).
- Added it as **version 2** of the secret; **version 1 was disabled**.
- `co-author-hash-salt-dev` version 1 was already valid and untouched.

### 3. Image built locally and pushed (Cloud Build blocked)

`gcloud builds submit` failed twice on IAM, so the image was built with
local Docker and pushed with owner credentials instead:

```
docker build -f collectors/youtube/Dockerfile -t \
  europe-central2-docker.pkg.dev/pop-vibe-check/co-images-dev/youtube-collector:729b1fdc5d8250915d0a59fa68d2408489b0a1f4 .
docker push ...
```

Why Cloud Build failed (known gap, fix in Terraform if CI builds are wanted):

- The project uses the post-2024 Cloud Build default, so manual submits run
  as the **compute default SA**, which cannot read the
  `gs://pop-vibe-check_cloudbuild` staging bucket.
- The dedicated `co-cloud-build-sa-dev` SA hits the same wall: it has
  Artifact Registry writer (Terraform) but lacks
  `roles/storage.objectViewer` on the staging bucket and
  `roles/logging.logWriter` on the project.
- The legacy `891032629527@cloudbuild.gserviceaccount.com` SA has
  `cloudbuild.builds.builder` but is Google-managed and rejected by
  `--service-account`.

Required grants for `co-cloud-build-sa-dev` (add to the iam module):
`roles/storage.objectViewer` on `gs://pop-vibe-check_cloudbuild` and
`roles/logging.logWriter` on the project.

Windows note: `docker push` to Artifact Registry needs
`docker-credential-gcloud` on `PATH` — it lives in
`...\Google\Cloud SDK\google-cloud-sdk\bin`, which is not on `PATH` by
default on this machine.

### 4. Cloud Run Job pinned to the image

- `terraform/envs/dev/main.tf` now sets `youtube_image_uri` to the
  `729b1fd...` tag (replacing the `pause` placeholder default).
- The live job was updated in place with `gcloud run jobs update`, so the
  next `terraform apply` reconciles with no diff on the image field.
- `reddit_image_uri` stays on the `pause` placeholder.

---

## Collection runs (2026-07-05)

Executed with `gcloud run jobs execute co-youtube-collector-dev
--update-env-vars="EVENT_ID=...,WINDOW_FROM=...,WINDOW_TO=..." --wait`.
All four executions succeeded:

| Event | Window (UTC) | Records |
|---|---|---|
| `launch` | 2025-04-24 → 2025-04-26 | 909 |
| `xbox_showcase_reveal` | 2024-06-09 → 2024-06-16 | 1711 |
| `gameplay_trailer_flying_waters` | 2024-08-27 → 2024-09-03 | 1257 |
| `critical_acclaim_wave` | 2025-05-12 → 2025-06-16 | 351 |

**Total: 4228 records** in
`gs://co-raw-archive-dev/youtube/<event>/2026/07/05/09/*.jsonl.gz`.

Windows are a first, defensible cut (a week from the event date; longer for
the acclaim wave to cover the 2025-06-02 GameSpot review). Re-running with
different windows only appends new batch files — dedupe by record `id`
belongs to the Phase 1 pipeline.

A sample record was pulled and inspected: schema matches the README contract,
`author_hash` is a 16-char salted hash (no raw handle), `created_utc` falls
inside the requested window, `parent_id` null for top-level comments.

Caveat spotted in the sample: `langdetect` labelled a short all-caps English
comment as `de`. Known weakness of langdetect on short texts — treat the
`language` field as advisory and revisit language filtering in Phase 1.

---

## Updated DoD status (YouTube side)

| DoD item | Status |
|---|---|
| `config/youtube_videos.yaml` with ≥5 canonical videos | Done — 9 verified ids, 1 placeholder left (`ai_textures_controversy`) |
| Smoke test against real APIs (small window) | Done — four real runs, 4228 records |
| Images built and pushed to Artifact Registry | Done for YouTube (local Docker; Cloud Build blocked by IAM, see above) |
| `terraform apply` with image URI overrides | `main.tf` updated; job already updated in place via gcloud — apply is a no-op reconcile |
| `gcloud run jobs execute` produces a valid `.jsonl.gz` | Done — verified against the record schema |

## Remaining

1. Reddit: obtain API credentials, replace the placeholder secret values,
   build/push the image, repeat the same flow.
2. Decide on `ai_textures_controversy` (find an April-2025 video or retarget
   to the December 2025 TGA wave).
3. Optional: add the two IAM grants above so Cloud Build works for CI.
4. Verify the `# VERIFY`-flagged event dates in `events.yaml` (still open
   from the previous iteration).
