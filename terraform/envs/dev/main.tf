locals {
  env = "dev"

  # Project-wide labels applied to every resource that supports them.
  # Kept here (not duplicated in each module call) so the composition root
  # is the single source of truth for environment-wide tagging.
  labels = {
    project    = "co-sentiment"
    env        = local.env
    owner      = "team-198019-198265-198223"
    managed_by = "terraform"
  }
}

# Application modules are composed here as Phase 0 and Phase 1 work lands.
# The initial composition is intentionally empty: this configuration is
# committed to validate that the remote state backend and runner SA
# impersonation work end-to-end before any resources are created.
