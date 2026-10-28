# ADR 0004 — MLflow runs as a tracking server on Cloud Run, backed by Cloud SQL

- **Status:** Accepted
- **Date:** 2026-10-28
- **Affects:** `terraform/modules/mlflow`, `mlflow_server/`,
  `nlp/tracking/`, the monthly budget
- **Relates to:** the thesis statement, which names deploying the MLflow
  platform to manage the model lifecycle and track experiments as a key
  element of the project; open decision 5 in
  [`phase-1-plan.md`](../phase-1-plan.md)

## Context

MLflow was used, but not deployed. Training logged parameters, metrics and
weights through `nlp/tracking/mlflow_utils.py`. The tracking store was a
directory on the Workbench VM's disk; only the artifacts were in GCS.
That had three consequences:

- **Nobody else could see it.** The UI ran only as `mlflow ui` on a
  stopped-by-default VM behind IAP SSH. Neither a supervisor nor a
  reviewer could open a link to it.
- **The history was one disk away from loss.** The XLM-R runs' metadata
  existed only on that disk. A manual copy to GCS covered the DistilBERT
  run alone.
- **It was not infrastructure.** Everything else in the project is
  Terraform; MLflow was a convention on one machine. The model versions
  lived in Vertex Model Registry, uploaded by a script, and MLflow's own
  registry was unused.

Phase 1 left the hosting decision open: Cloud Run plus Cloud SQL was named
as the correct shape, but deferred for its recurring cost.

## Decision

**The MLflow tracking server runs on Cloud Run, with Cloud SQL Postgres as
its backend store, behind IAP, all in Terraform** (`modules/mlflow`).

- **Metadata and the registry in Postgres**, on a permanently running
  `db-f1-micro` instance. The server is reachable whenever the project is.
- **Artifacts stay in GCS under `nlp/mlruns/`**, and the server does not
  proxy them (`--no-serve-artifacts`). Weights are gigabytes and Cloud
  Run caps a request at 32 MiB; clients already have write access there.
- **IAP decides who gets in**, with the dashboard's OAuth client and viewer
  list. Programs authenticate with a Google ID token for the IAP client.
- **The existing runs are copied over** (`nlp/tracking/migrate.py`).

### Alternatives considered

- **Cloud SQL switched off between uses** (an `activation_policy` gate,
  like the Workbench's). It costs only the disk while it is off, but then
  the UI is down whenever nobody remembered to turn it on. Rejected: a
  platform that is usually off is not a deployed platform.
- **SQLite on a GCS volume, no Cloud SQL.** It costs nothing, but GCS has
  no file locking, so concurrent writes can corrupt the database. It also
  does not fit the stated requirement for a deployed platform. Rejected.
- **Leave it on Workbench.** Rejected for the three reasons in Context.

## Consequences

- **A standing cost:** roughly 40–55 PLN a month for the instance and its
  disk, about the whole previous dev budget. The budget is raised to match;
  the service itself scales to zero.
- **Every IAP viewer can edit runs.** This setup has no MLflow permissions.
  Daily backups and soft deletes bound the damage.
- **Server and client versions are coupled.** The server pin is the
  training client's upper bound, and schema upgrades are a manual
  `mlflow db upgrade`.
- **Run ids change in the migration.** The old id and artifact URI are
  kept as tags on each copied run.
