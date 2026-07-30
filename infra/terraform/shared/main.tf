/*
Resources genuinely shared by BOTH environments (free-tier, full-textbook):
one ECR repository (one image, two deploy targets pull the same tag) and
one GitHub Actions OIDC identity provider (one trust relationship,
re-used by a separate least-privilege deploy role per environment --
those roles live in each environment's own config, since their
permissions reference resources -- the EC2 instance, the ECS service --
that don't exist until that environment is actually built).

Applied once, before either environment. Own remote state (key
"shared/terraform.tfstate") so free-tier and full-textbook can each
depend on it via a `data "terraform_remote_state"` lookup without ever
depending on EACH OTHER's state.
*/

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "anhnguyen-terraform-state-884135111378"
    key            = "shared/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "terraform-state-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = "us-east-2"
}

# --- ECR ------------------------------------------------------------------

resource "aws_ecr_repository" "app" {
  name                 = "money-tracking-app"
  image_tag_mutability = "MUTABLE" # simple "main" branch, no immutable-tag release process (yet) -- MUTABLE is the right default until one exists

  image_scanning_configuration {
    scan_on_push = true # free vulnerability scanning, no reason not to
  }
}

# Keeps the repo small (ECR's small always-free tier only covers so much
# storage) and keeps `docker images`/console listings readable -- expires
# untagged layers quickly (they're only ever build-time intermediates
# once a real tag exists) and caps how many tagged images stick around.
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the last 10 tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["main"]
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = { type = "expire" }
      }
    ]
  })
}

# --- GitHub Actions OIDC ----------------------------------------------------

# GitHub's OIDC thumbprint -- AWS validates the token's issuer against
# this, not against GitHub's TLS cert chain directly. This is GitHub's
# published, stable value for token.actions.githubusercontent.com.
resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# --- Cost safety net --------------------------------------------------------

# Account-wide, not per-environment, since it's meant to catch total
# spend across everything -- free-tier's steady-state cost (should stay
# near $0) AND full-textbook's temporary, much larger cost while it's up.
# $100/month is a round number chosen as "if we hit this, something is
# definitely worth reviewing" -- NOT a hard cap (AWS Budgets alerts, it
# doesn't enforce/block spend on its own). Three escalating signals:
# - 25% ($25) -- would already be surprising with only free-tier running;
#   an early flag that something unexpected is accruing cost.
# - 75% ($75) -- roughly where full-textbook's ~1 week of exploration
#   was expected to land; a sign the temporary environment either cost
#   more than estimated or teardown is running late.
# - 100% forecasted -- an early warning BEFORE the actual dollars
#   accrue, based on the current month's spend trajectory, so this can
#   catch a slipping teardown a few days sooner than waiting for the
#   actual-cost thresholds to be crossed for real.
resource "aws_budgets_budget" "monthly_cost" {
  name         = "money-tracking-app-monthly"
  budget_type  = "COST"
  limit_amount = "100"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 25
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["mrfruitypotato@gmail.com"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 75
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["mrfruitypotato@gmail.com"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = ["mrfruitypotato@gmail.com"]
  }
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "ecr_repository_arn" {
  value = aws_ecr_repository.app.arn
}

output "ecr_repository_name" {
  value = aws_ecr_repository.app.name
}

output "github_oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.github_actions.arn
}
