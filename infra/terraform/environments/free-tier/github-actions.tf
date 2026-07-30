/*
GitHub Actions deploy role for THIS environment only -- full-textbook gets
its own separate role (different permissions: ECS instead of SSM) when
that environment is built, both trusting the one shared OIDC provider
from infra/terraform/shared.

The role deliberately does NOT get any Terraform state read access. CI
needs the instance ID to target with SSM, but rather than granting this
role s3:GetObject on the state bucket just for that one lookup, the
instance ID (and this role's own ARN) are pasted into GitHub as plain,
non-secret repository Variables once after `apply` -- see the outputs
below. Neither value is sensitive; both are already visible to anyone
who can read this state file or the AWS console.
*/

data "aws_iam_policy_document" "github_actions_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.terraform_remote_state.shared.outputs.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Scoped to this specific repo AND the main branch -- not a blanket
    # "repo:anhtn99/money-tracking-app:*" trust. workflow_dispatch runs
    # carry the ref of whichever branch was selected when triggering, so
    # this also means "deploy" can only ever be manually run against main.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:anhtn99/money-tracking-app:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions_deploy" {
  name               = "${local.name_prefix}-github-actions-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume.json
}

data "aws_iam_policy_document" "github_actions_deploy" {
  # GetAuthorizationToken has no resource-level permissions -- it's the
  # one ECR action AWS requires "*" for, regardless of which repos you
  # actually intend to push to.
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPush"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
    ]
    resources = [data.terraform_remote_state.shared.outputs.ecr_repository_arn]
  }

  # SendCommand supports resource-level scoping -- restricted to exactly
  # this instance and the one AWS-owned document the deploy script uses,
  # instead of "*" across every instance/document in the account.
  statement {
    sid     = "SsmSendCommand"
    effect  = "Allow"
    actions = ["ssm:SendCommand"]
    resources = [
      "arn:aws:ec2:us-east-2:${data.aws_caller_identity.current.account_id}:instance/${module.ec2_app.instance_id}",
      "arn:aws:ssm:us-east-2::document/AWS-RunShellScript",
    ]
  }

  # GetCommandInvocation/ListCommandInvocations don't support
  # resource-level restriction at all (AWS docs list them as "*"-only) --
  # this is the read-only status check the deploy script polls with
  # after SendCommand, not an additional execution capability.
  statement {
    sid       = "SsmCommandStatus"
    effect    = "Allow"
    actions   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy" {
  name   = "${local.name_prefix}-github-actions-deploy"
  role   = aws_iam_role.github_actions_deploy.id
  policy = data.aws_iam_policy_document.github_actions_deploy.json
}
