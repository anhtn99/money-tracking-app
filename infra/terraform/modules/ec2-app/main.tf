/*
The free-tier environment's compute: one EC2 instance, its security
group, its IAM instance profile, and an Elastic IP so the DNS record
survives any future instance replacement.

No SSH (port 22) anywhere in this module -- all remote command execution
(manual ops AND CI/CD deploys) goes through AWS Systems Manager Run
Command instead, which only needs outbound connectivity from the
instance's SSM agent, not an inbound port. That's what
AmazonSSMManagedInstanceCore below grants. See infra/ARCHITECTURE.md for
the full reasoning against SSH here.
*/

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  # "al2023-ami-*-x86_64" (without the "2023." right after "ami-") also
  # matches the MINIMAL variant ("al2023-ami-minimal-2023...."), which
  # strips out several packages including the pre-installed SSM agent --
  # this bit us for real during Phase 7 (an instance with no SSH and no
  # working SSM agent has literally no remote access path at all). This
  # pattern requires "2023." immediately after "ami-", which the minimal
  # variant's name doesn't have, so it can only match the standard image.
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# --- Security group ---------------------------------------------------------

resource "aws_security_group" "app" {
  name_prefix = "${var.name_prefix}-app-"
  vpc_id      = var.vpc_id
  description = "Free-tier app instance -- HTTPS/HTTP only, no SSH (SSM Run Command handles remote exec instead)"

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP -- Lets Encrypt HTTP-01 challenge only, Caddy redirects everything else to HTTPS"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

# --- IAM instance profile ----------------------------------------------------

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name_prefix        = "${var.name_prefix}-app-"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

# AWS-managed policy -- registers the instance with SSM and enables Run
# Command / Session Manager. This is the ONLY way this instance is
# remotely administered (deploys, one-off commands); no SSH key exists
# for it anywhere.
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "app_permissions" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # AWS requirement -- this specific action has no resource-level scoping
  }

  statement {
    sid = "EcrPull"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [var.ecr_repository_arn]
  }

  statement {
    sid = "AppConfigParameters"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParametersByPath",
    ]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/money-tracking-app/${var.environment}/*",
    ]
  }

  # The app's own runtime code (app/core/secrets.py) creates/reads Plaid
  # access token parameters at Plaid Link time -- separate from the
  # deploy-time config parameters above, matching the scoping that used
  # to be on the ECS task role for the same purpose.
  statement {
    sid = "PlaidAccessTokenParameters"
    actions = [
      "ssm:GetParameter",
      "ssm:PutParameter",
    ]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/money-tracking-app/plaid-access-token/*",
    ]
  }
}

resource "aws_iam_role_policy" "app_permissions" {
  name   = "${var.name_prefix}-app-permissions"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app_permissions.json
}

resource "aws_iam_instance_profile" "app" {
  name_prefix = "${var.name_prefix}-app-"
  role        = aws_iam_role.app.name
}

# --- Instance + Elastic IP ---------------------------------------------------

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    docker_compose_content = file(var.docker_compose_prod_path)
    caddyfile_content      = file(var.caddyfile_path)
  })
  # Replaces the instance if the compose file/Caddyfile actually change
  # (not on every apply) -- deliberate: this instance is meant to be
  # long-running, not recreated on every unrelated infra tweak.
  user_data_replace_on_change = true

  tags = { Name = "${var.name_prefix}-app" }
}

resource "aws_eip" "app" {
  instance = aws_instance.app.id
  domain   = "vpc"

  tags = { Name = "${var.name_prefix}-app-eip" }
}
