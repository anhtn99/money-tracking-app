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

data "aws_caller_identity" "current" {}

# --- Terraform CI/CD (infra changes, as opposed to app deploys) -----------
#
# Deliberately two separate roles with very different trust conditions,
# not one role reused for both:
#
# - terraform-plan is read-only (AWS managed ReadOnlyAccess) and trusted
#   from ANY pull request touching infra/terraform/** -- safe to trust
#   broadly because the permissions themselves can't mutate anything,
#   regardless of which branch opened the PR.
# - terraform-apply can actually create/modify/destroy real
#   infrastructure, so its trust condition is anchored to a GitHub
#   *environment* name (`infra-production`, configured in the GitHub UI
#   with a required reviewer), not a branch. GitHub only mints an OIDC
#   token with that `environment:` sub claim once a job has passed that
#   environment's protection rules -- i.e. once a human has clicked
#   Approve. This is the same "stop and confirm before apply" guarantee
#   this whole phase has followed by hand, enforced by GitHub itself
#   instead of by a person watching chat.
#
# Both live here (not per-environment, unlike the app-deploy role) because
# apply's permissions can't be scoped to specific resource ARNs the way
# the free-tier deploy role's SSM permissions were -- Terraform is what
# CREATES those resources, so their IDs don't exist yet at the point
# permissions have to be defined. One shared pair of roles, reused for
# whichever environment directory a given plan/apply run targets.

data "aws_iam_policy_document" "terraform_plan_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # pull_request-triggered jobs get this fixed sub claim regardless of
    # the PR's source branch -- intentional, a plan needs to run on every
    # PR, not just ones opened from main.
    #
    # Uses GitHub's "immutable ID" subject format (owner@owner_id and
    # repo@repo_id, not the plain name slug) -- confirmed by decoding an
    # actual token from this repo's own Actions runs. GitHub embeds the
    # account's/repo's stable numeric IDs specifically so a rename (this
    # repo WAS briefly renamed to shared-expenses-sheet and back) can't
    # leave a stale trust policy matching whatever repo/account picks up
    # the old name later. owner_id 306890925, repo_id 1306216379.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:anhtn99@306890925/money-tracking-app@1306216379:pull_request"]
    }
  }
}

resource "aws_iam_role" "terraform_plan" {
  name               = "money-tracking-app-terraform-plan"
  assume_role_policy = data.aws_iam_policy_document.terraform_plan_assume.json
}

resource "aws_iam_role_policy_attachment" "terraform_plan_readonly" {
  role       = aws_iam_role.terraform_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# `terraform plan` doesn't change any AWS resource, but it still has to
# acquire this backend's DynamoDB state lock to safely read state --
# ReadOnlyAccess correctly excludes DynamoDB writes (it's genuinely
# read-only), so this is a narrow, explicit exception for exactly the
# lock table, not a general DynamoDB write grant.
data "aws_iam_policy_document" "terraform_plan_state_lock" {
  statement {
    sid       = "TerraformStateLock"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = ["arn:aws:dynamodb:us-east-2:${data.aws_caller_identity.current.account_id}:table/terraform-state-lock"]
  }
}

resource "aws_iam_role_policy" "terraform_plan_state_lock" {
  name   = "money-tracking-app-terraform-plan-state-lock"
  role   = aws_iam_role.terraform_plan.id
  policy = data.aws_iam_policy_document.terraform_plan_state_lock.json
}

# free-tier's main.tf reads the actual RDS master password (via
# manage_master_user_password's AWS-managed Secrets Manager secret) to
# compose DATABASE_URL for the SSM secrets module -- `terraform plan`
# needs the real value to know whether that derived SSM parameter would
# change, so this is a genuine exception to "read-only", not operational
# plumbing like the state lock above.
#
# Scoped to the `rds!` name prefix specifically, not this one secret's
# exact ARN or a blanket `secret:*` -- AWS reserves that literal prefix
# for secrets it creates itself via manage_master_user_password, a
# regular IAM principal can't create a secret matching that name. Covers
# full-textbook's future Aurora-managed secret too, and avoids reaching
# across into free-tier's separate state from here (shared is applied
# before either environment exists, so it can't depend on their outputs).
data "aws_iam_policy_document" "terraform_plan_rds_secret" {
  statement {
    sid       = "ReadRdsManagedSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:us-east-2:${data.aws_caller_identity.current.account_id}:secret:rds!*"]
  }
}

resource "aws_iam_role_policy" "terraform_plan_rds_secret" {
  name   = "money-tracking-app-terraform-plan-rds-secret"
  role   = aws_iam_role.terraform_plan.id
  policy = data.aws_iam_policy_document.terraform_plan_rds_secret.json
}

data "aws_iam_policy_document" "terraform_apply_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # See the matching comment on terraform_plan_assume above -- same
    # immutable-ID subject format, confirmed against a real token from
    # this repo.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:anhtn99@306890925/money-tracking-app@1306216379:environment:infra-production"]
    }
  }
}

resource "aws_iam_role" "terraform_apply" {
  name               = "money-tracking-app-terraform-apply"
  assume_role_policy = data.aws_iam_policy_document.terraform_apply_assume.json
}

resource "aws_iam_role_policy_attachment" "terraform_apply_poweruser" {
  role       = aws_iam_role.terraform_apply.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

# PowerUserAccess deliberately excludes ALL of IAM (via a NotAction, not a
# Deny -- so this supplemental policy layers on top correctly) specifically
# to stop a broadly-permissioned pipeline role from being able to grant
# itself more access than it started with. This project's Terraform does
# need to manage a handful of IAM resources though (the EC2 instance role,
# this role's sibling deploy role, etc.), so this grants exactly those
# actions -- restricted to resources whose name already carries this
# project's "money-tracking-app-" prefix. It cannot touch any IAM
# role/policy/instance-profile belonging to anything else in the account.
data "aws_iam_policy_document" "terraform_apply_iam_scoped" {
  statement {
    sid    = "ManageProjectIamRoles"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:TagRole",
      "iam:UpdateRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:PutRolePolicy",
      "iam:GetRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:PassRole",
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/money-tracking-app-*",
    ]
  }

  statement {
    sid    = "ManageProjectInstanceProfiles"
    effect = "Allow"
    actions = [
      "iam:CreateInstanceProfile",
      "iam:DeleteInstanceProfile",
      "iam:GetInstanceProfile",
      "iam:AddRoleToInstanceProfile",
      "iam:RemoveRoleFromInstanceProfile",
      "iam:TagInstanceProfile",
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/money-tracking-app-*",
    ]
  }
}

resource "aws_iam_role_policy" "terraform_apply_iam_scoped" {
  name   = "money-tracking-app-terraform-apply-iam-scoped"
  role   = aws_iam_role.terraform_apply.id
  policy = data.aws_iam_policy_document.terraform_apply_iam_scoped.json
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

output "terraform_plan_role_arn" {
  value       = aws_iam_role.terraform_plan.arn
  description = "Paste into the GitHub repo's Actions > Variables as TERRAFORM_PLAN_ROLE_ARN"
}

output "terraform_apply_role_arn" {
  value       = aws_iam_role.terraform_apply.arn
  description = "Paste into the GitHub repo's Actions > Variables as TERRAFORM_APPLY_ROLE_ARN"
}
