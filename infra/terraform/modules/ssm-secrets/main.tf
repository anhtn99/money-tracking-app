/*
Terraform-managed SSM SecureString parameters for one environment's app
config -- DATABASE_URL and the Plaid client credentials. Extends the
naming convention already established by app/core/secrets.py's own
runtime-managed Plaid access token parameters
(/money-tracking-app/plaid-access-token/{item_id}), but namespaced per
environment (free-tier vs full-textbook each get their own DB and
possibly-different Plaid sandbox/production credentials).

Note on SSM vs. Secrets Manager here specifically: ECS task definitions
CAN pull a single JSON key out of a Secrets Manager secret via a
`:key::` suffix on the ARN, but SSM's `secrets`/`valueFrom` injection has
no equivalent -- a referenced SSM parameter's ENTIRE value becomes the
env var, no JSON-key extraction. That's why this is three separate
parameters (database-url, plaid-client-id, plaid-secret) instead of one
combined JSON blob the way a Secrets-Manager-based design might do it.
*/

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "aws_ssm_parameter" "database_url" {
  name  = "/money-tracking-app/${var.environment}/database-url"
  type  = "SecureString"
  value = var.database_url

  # The value gets recomposed from the DB module's own outputs on every
  # apply (see environments/*/main.tf) -- lifecycle.ignore_changes isn't
  # used here on purpose, so a genuine password rotation actually
  # propagates instead of being silently ignored.
}

resource "aws_ssm_parameter" "plaid_client_id" {
  name  = "/money-tracking-app/${var.environment}/plaid-client-id"
  type  = "SecureString"
  value = var.plaid_client_id
}

resource "aws_ssm_parameter" "plaid_secret" {
  name  = "/money-tracking-app/${var.environment}/plaid-secret"
  type  = "SecureString"
  value = var.plaid_secret
}
