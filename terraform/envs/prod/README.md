# terraform/envs/prod

The production composition. Same modules as [`../dev`](../dev), same
wiring, `prod` instead of `dev` in every resource name.

Its first purpose is the one the thesis cares about: **proving the system
is reproducible.** A complete environment — buckets, dataset and tables,
topics and subscriptions, service accounts, secrets, network, jobs,
alerts, budget — stands up from committed code in one apply, against an
empty state.

## How prod differs from dev

| | dev | prod |
|---|---|---|
| Applied by | Cloud Build, approval-gated | an operator, by hand |
| CI/CD module | yes — connection, triggers, image deploys | **no** |
| Vertex AI Workbench / Endpoint | gated, created on demand | **no** — training and serving stay in dev |
| Job images | deployed by digest on every merge | `pause` placeholder until pointed at a digest |
| Subnet | `10.10.0.0/24` | `10.20.0.0/24` |
| Dataflow runtime alert | 6h | 3h |

The three absences are deliberate. Images are built once and are not
per-environment artifacts, so a second set of triggers would duplicate
work to no benefit; a second idle Vertex Endpoint would bill for nothing;
and an approval-gated prod pipeline is worth building only when something
actually runs here continuously.

**State** lives under the `prod/` prefix of the shared bucket
(`pvc-tf-state`), so dev and prod cannot touch each other's state. Both
impersonate the same runner service account, so what creates the resources
is identical.

## Apply it

```bash
cp terraform.tfvars.example terraform.tfvars   # fill in project and billing
terraform init
terraform plan
terraform apply
```

**One step comes between plan and apply the first time.** Terraform owns
the secret *containers* but never their values, and Cloud Run resolves a
job's `secret_key_ref` when the job is **created** — so an apply against
secrets that have no version fails three times over:

```
Error waiting to create Job: Secret .../co-author-hash-salt-prod/versions/latest was not found
```

Give each one a version first. Placeholders are enough to stand the
environment up; real values are only needed before a collection actually
runs here:

```bash
for s in co-reddit-client-id-prod co-reddit-client-secret-prod \
         co-reddit-user-agent-prod co-youtube-api-key-prod \
         co-author-hash-salt-prod; do
  printf 'PLACEHOLDER - replace before any prod collection run' \
    | gcloud secrets versions add "$s" --project=<PROJECT_ID> --data-file=-
done
```

Before collecting in prod, replace the YouTube key and — deliberately —
decide what the **author-hash salt** should be. A salt different from
dev's means author identities do not line up across the two environments;
the same salt means they do. Neither is wrong, but it is a choice, and
rotating it later invalidates author continuity in whatever has already
been collected.

You need `roles/iam.serviceAccountTokenCreator` on `pvc-tf-runner-sa`;
`roles/owner` alone does **not** grant impersonation. See
[`../dev/README.md`](../dev/README.md) for that grant and for the one-time
auth steps.

A first apply on an empty state creates the whole environment (94
resources, verified 2026-10-12). Nothing in
it costs money while idle: the buckets and tables are empty, the jobs are
placeholders that never execute on their own, and no Dataflow job exists —
`terraform apply` never starts one, here or in dev.

## Running something in prod

1. Point `youtube_image_uri`, `steam_image_uri` and `publisher_image_uri`
   at Artifact Registry digests (dev images work — the registry is
   per-environment but readable within the project), then apply.
2. Execute the collectors and the publisher with
   `gcloud run jobs execute co-<job>-prod`, exactly as in dev.
3. Launch the pipeline with `dataflow/launch.sh --env-dir terraform/envs/prod`;
   it reads every launch parameter from this composition's outputs.
4. Promote with `dataflow/promote.sh --env-dir terraform/envs/prod`.

The replay build (`co-replay-dev`) is dev-only, so a prod replay is the
manual sequence those two scripts exist for. The ordering rule still
holds and is the operator's responsibility here: promote **after** the job
drains, never when the publisher exits. See
[ADR 0002](../../docs/adr/0002-replay-runs-as-one-build-with-a-completeness-gate.md).

## Tearing down

`terraform destroy` refuses while buckets hold objects — deliberately.
The `force_destroy_*` variables on the storage module lift that for a
one-off apply plus destroy; `delete_contents_on_destroy` does the same for
the BigQuery dataset. Do not leave either set in committed code.
