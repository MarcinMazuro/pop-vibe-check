# modules/secrets

Provisions Secret Manager **containers** for collector credentials and the
author-hash salt. Container only — secret values are populated manually
per env.

## What this creates

Five secrets, all named `${name_prefix}-{purpose}-${env}`:

- **`{name_prefix}-reddit-client-id-{env}`** — OAuth client ID for the Reddit app
- **`{name_prefix}-reddit-client-secret-{env}`** — OAuth client secret
- **`{name_prefix}-reddit-user-agent-{env}`** — user-agent string Reddit requires for OAuth
- **`{name_prefix}-youtube-api-key-{env}`** — YouTube Data API v3 key
- **`{name_prefix}-author-hash-salt-{env}`** — random ≥32-byte salt; SHA-256-hashed with usernames at ingest. Single use, never rotated unless a security incident forces it (rotation invalidates author continuity across the dataset).

Plus six `roles/secretmanager.secretAccessor` bindings:

| Secret | Grantee |
|---|---|
| `reddit-client-id` | Reddit collector SA |
| `reddit-client-secret` | Reddit collector SA |
| `reddit-user-agent` | Reddit collector SA |
| `youtube-api-key` | YouTube collector SA |
| `author-hash-salt` | Reddit **and** YouTube collector SAs (both collectors hash usernames) |

All replication is `auto` (Google-managed multi-region key). CMEK upgrade can be a later ADR.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `name_prefix` | string | yes | — | Short release prefix (2-8 chars, lowercase alphanumeric/hyphen) |
| `env` | string | yes | — | Environment name; suffixed into secret IDs |
| `labels` | map(string) | yes | — | Labels applied to every secret container |
| `collector_reddit_sa_email` | string | yes | — | Reddit collector SA email (from `iam` module) |
| `collector_youtube_sa_email` | string | yes | — | YouTube collector SA email (from `iam` module) |

## Outputs

| Name | Description |
|---|---|
| `secret_ids` | Map of short name → fully-qualified secret resource ID |
| `secret_names` | Map of short name → the actual secret_id with prefix and env. Use these in `gcloud secrets versions add` |

## Post-apply: populate the values

The module creates **empty** containers. You must add a version to each
secret exactly once per env. From any shell with `gcloud` authenticated:

```bash
# Read each value from your password manager / Reddit app dashboard /
# YouTube console and pipe it in. Do NOT echo the value on the command line.

printf '%s' "$REDDIT_CLIENT_ID" | gcloud secrets versions add \
  co-reddit-client-id-dev --project=<PROJECT_ID> --data-file=-

printf '%s' "$REDDIT_CLIENT_SECRET" | gcloud secrets versions add \
  co-reddit-client-secret-dev --project=<PROJECT_ID> --data-file=-

printf '%s' "$REDDIT_USER_AGENT" | gcloud secrets versions add \
  co-reddit-user-agent-dev --project=<PROJECT_ID> --data-file=-

printf '%s' "$YOUTUBE_API_KEY" | gcloud secrets versions add \
  co-youtube-api-key-dev --project=<PROJECT_ID> --data-file=-

# Author-hash salt: generate locally, paste once, then forget.
openssl rand -hex 32 | gcloud secrets versions add \
  co-author-hash-salt-dev --project=<PROJECT_ID> --data-file=-
```

Substitute `co` with your `name_prefix` and `dev` with your env if different.

## Notes

- **Values are never in tfvars, env files, or commits** — only secret IDs flow through Terraform. State files contain the secret resource IDs but not their values; secret values live only in Secret Manager.
- **Author-hash salt rotation:** treat as immutable. If you must rotate, expect every historical `author_hash` in BigQuery to no longer match new collections — author continuity is gone.
- **Bindings are accessor-only.** Workload SAs cannot list, describe, or modify secrets — only read the current version. Adding/removing secret versions stays a human-with-gcloud operation.
