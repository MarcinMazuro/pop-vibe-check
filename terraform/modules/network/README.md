# modules/network

Provisions one VPC and one regional subnet with Private Google Access.

## What this creates

- **`{name_prefix}-vpc-{env}`** — custom-mode VPC (`auto_create_subnetworks = false`), so the only subnet that exists is the one declared by this module.
- **`{name_prefix}-subnet-{env}`** — single regional subnet with `private_ip_google_access = true`. Workloads in this subnet reach Google APIs (Secret Manager, GCS, BigQuery, Pub/Sub, …) via Google's internal backbone instead of public internet — no external IP required on a Dataflow worker.
- **`{name_prefix}-allow-dataflow-internal-{env}`** — firewall rule allowing worker-to-worker traffic on TCP 12345-12346 (the Beam harness ports), scoped to the subnet CIDR and the `dataflow` network tag. See "Why the Dataflow firewall rule is mandatory" below.

No Cloud NAT — Private Google Access covers the Google APIs the workloads reach.

## Why the Dataflow firewall rule is mandatory

A custom-mode VPC (`auto_create_subnetworks = false`) ships with **no firewall rules at all** — not even the `allow-internal` set that the auto-mode `default` network provides. The only implied behaviour is allow-all-egress and deny-all-ingress. Dataflow workers communicate over TCP 12345-12346, so without an explicit allow rule that traffic is denied and **the job hangs in "starting"/"running" until it times out** — no error, just a stall. This rule is that allow, scoped to ingress from the subnet CIDR (not `0.0.0.0/0`) onto the `dataflow` tag that the Dataflow service applies to worker VMs automatically. It is created unconditionally: the rule is free, gating it only reintroduces the hang, and there is no toggle to misconfigure.

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
| `subnet_cidr` | Primary CIDR of the subnet |
| `dataflow_worker_tag` | Network tag the intra-worker firewall rule targets (`dataflow`); the dataflow module references this |

## Notes

- **Primary consumer is Dataflow** (Phase 1) — Dataflow jobs must specify a network/subnet. Cloud Run collectors can run without VPC (default Cloud Run egress already reaches `*.googleapis.com`), so this module is not on their critical path; it lands now so Dataflow doesn't block on it later.
- **No labels on the VPC/subnet.** `google_compute_network` and `google_compute_subnetwork` don't accept labels in provider v5 — documented exception to the project-wide labelling convention. (`google_compute_firewall` has no labels field either.)
- **Single subnet, single region.** Cross-region replication is explicitly out of scope for the thesis.
