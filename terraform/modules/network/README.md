# modules/network

Provisions one VPC and one regional subnet with Private Google Access.

## What this creates

- **`{name_prefix}-vpc-{env}`** — custom-mode VPC (`auto_create_subnetworks = false`), so the only subnet that exists is the one declared by this module.
- **`{name_prefix}-subnet-{env}`** — single regional subnet with `private_ip_google_access = true`. Workloads in this subnet reach Google APIs (Secret Manager, GCS, BigQuery, Pub/Sub, …) via Google's internal backbone instead of public internet — no external IP required on a Dataflow worker.

No Cloud NAT, no firewall rules beyond the default implicit `allow-egress` / `allow-internal` of a fresh VPC. Add specific rules in this module when a workload actually needs them.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `name_prefix` | string | yes | — | Short release prefix |
| `env` | string | yes | — | Environment name; suffixed into resource names |
| `region` | string | yes | — | Region for the subnet |
| `subnet_cidr` | string | no | `10.10.0.0/24` | Subnet CIDR. /24 is plenty for Dataflow ≤ 5 workers plus the occasional Cloud Run Direct VPC task |

## Outputs

| Name | Description |
|---|---|
| `network_id` | Fully-qualified VPC resource ID |
| `network_self_link` | Self-link URL — Dataflow `network` field wants this |
| `network_name` | Short VPC name |
| `subnet_id` | Fully-qualified subnet resource ID |
| `subnet_self_link` | Self-link URL — Dataflow `subnetwork` and Cloud Run Direct VPC egress want this |
| `subnet_name` | Short subnet name |

## Notes

- **Primary consumer is Dataflow** (Phase 1) — Dataflow jobs must specify a network/subnet. Cloud Run collectors can run without VPC (default Cloud Run egress already reaches `*.googleapis.com`), so this module is not on their critical path; it lands now so Dataflow doesn't block on it later.
- **No labels.** `google_compute_network` and `google_compute_subnetwork` don't accept labels in provider v5 — documented exception to the project-wide labelling convention.
- **Single subnet, single region.** Cross-region replication is explicitly out of scope for the thesis.
