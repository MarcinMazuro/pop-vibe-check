# modules/budgets

Provisions a monthly billing budget with multi-threshold alerts plus email
notification channels for each recipient.

## What this creates

- **One `google_billing_budget`** filtered to the supplied project, with thresholds at 50% / 90% / 100% / 120% (configurable) of `monthly_amount`. Display name: `${name_prefix} ${env} monthly budget`.
- **One `google_monitoring_notification_channel`** of type `email` per address in `notification_emails`. Channels are project-scoped.

`disable_default_iam_recipients = true` on the budget — only the listed email channels get alerts. Billing admins on the account are **not** notified by default; opt in explicitly by adding their email to `notification_emails`.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | Project the budget filters on |
| `name_prefix` | string | yes | — | Short release prefix used in display names |
| `env` | string | yes | — | Environment name used in display names so dev/prod alerts are visually distinct |
| `billing_account_id` | string | yes | — | `XXXXXX-YYYYYY-ZZZZZZ`. The budget hangs off this account |
| `monthly_amount` | number | yes | — | Monthly cap in the billing account's default currency (PLN for Poland-billed accounts) |
| `threshold_percentages` | list(number) | no | `[0.5, 0.9, 1.0, 1.2]` | Decimal spend percentages at which alerts fire |
| `notification_emails` | list(string) | no | `[]` | Addresses that receive alerts |
| `include_credits` | bool | no | `true` | Whether GCP credits count against the budget |

## Outputs

| Name | Description |
|---|---|
| `budget_id` | Fully-qualified budget resource name |
| `notification_channel_ids` | Map of email → notification channel ID |

## After apply: verify the email channels

GCP creates email notification channels immediately, but **does not deliver**
until the recipient confirms ownership by clicking a verification link sent
by `notifications-noreply@google.com`. On first apply, expect:

1. Each address in `notification_emails` receives a "Confirm your Cloud
   Monitoring notification channel" message.
2. Recipient must click the embedded confirmation link.
3. Until they do, the channel exists in state and shows as verified=false
   in the Cloud Console; budget alerts will silently fail to deliver to
   that address.

Re-apply does not re-trigger the verification email. If a channel was
created but never verified, either click the resend link in the Cloud
Console or destroy & re-create the channel.

## Notes

- **Per-project filter, not per-release.** This budget covers every release that lives in `project_id`. If two case studies (`co-`, `w4-`) share the same GCP project, a single budget keeps overall spend visible; separate budgets would only differentiate by label-filter, which the GCP budgets API supports but at the cost of more moving parts than this thesis needs.
- **Currency comes from the billing account.** No `currency_code` input — the budget inherits the billing account's default currency. Mixing currencies in one budget is not supported by GCP.
- **`include_credits = true` is the conservative read.** The default counts free-tier and promotional credits against the cap, so alerts fire on the spend GCP *would* bill if credits ran out. Switch to `false` to alert only on real out-of-pocket spend.
- **No emergency pause Cloud Function.** Earlier IaC notes mention an optional Cloud Function that pauses Dataflow at 100%. Deliberately out of scope here — explicit, documented teardown of streaming jobs (manual `gcloud dataflow jobs cancel`) is enough for thesis ops and avoids the operational surprise of jobs disappearing mid-test.
