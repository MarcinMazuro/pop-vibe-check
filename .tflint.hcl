# tflint configuration.
#
# The GCP ruleset is what makes this worth running at all: the generic
# rules catch unused declarations and bad interpolation, the plugin knows
# that e.g. a machine type has to exist.
#
# Deep checking (which calls the GCP API to validate resource attributes)
# is deliberately off: it needs credentials, and a lint step that fails
# when a service account is missing is a lint step people start skipping.

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "google" {
  enabled = true
  version = "0.31.0"
  source  = "github.com/terraform-linters/tflint-ruleset-google"
}

config {
  call_module_type = "local"
}

# Variables carry descriptions and types throughout; this enforces it for
# anything added later.
rule "terraform_documented_variables" {
  enabled = true
}

rule "terraform_documented_outputs" {
  enabled = true
}

rule "terraform_typed_variables" {
  enabled = true
}

# Naming is a project convention (snake_case for Terraform identifiers,
# kebab-case for the GCP resource names the modules compose).
rule "terraform_naming_convention" {
  enabled = true
}
