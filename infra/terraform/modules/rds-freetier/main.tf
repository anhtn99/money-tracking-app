/*
Single-AZ RDS Postgres instance for the free-tier environment.

db.t3.micro is the default here specifically because it's the
longest-standing, most reliably free-tier-eligible instance class for
RDS (750 hrs/month for the account's first 12 months) -- confirm current
eligibility for your specific account/region in the Billing Console's
"Free Tier" page before applying; AWS has occasionally extended free-tier
eligibility to db.t4g.micro (cheaper, ARM/Graviton) in some
regions/cohorts, which is why it's a variable and not hardcoded.

Single-AZ (not Multi-AZ) is a deliberate cost choice, not an oversight --
Multi-AZ roughly doubles the cost and isn't covered by the free tier
either way. Real production Aurora Serverless v2 (modules/aurora, used by
full-textbook) is inherently more available than this; this environment
accepts the tradeoff of a single point of failure for the database in
exchange for staying at $0.

Postgres 16.x to match docker-compose.yml's postgres:16 and Aurora's own
engine version -- same behavior in every environment, local or deployed.
*/

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db-subnet-group"
  subnet_ids = var.subnet_ids
}

# Security group boundary is what actually enforces "only the app can
# reach the database" -- subnet placement (both DB and EC2 sit in the
# same public subnets here) is not the enforcement mechanism, the SG
# reference below is.
resource "aws_security_group" "db" {
  name_prefix = "${var.name_prefix}-db-"
  vpc_id      = var.vpc_id
  description = "Allows Postgres access only from the apps own security group"

  ingress {
    description     = "Postgres from the app"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.app_security_group_id]
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

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-postgres"
  engine         = "postgres"
  engine_version = "16"

  instance_class    = var.instance_class
  allocated_storage = 20 # free-tier ceiling -- also plenty for a 2-person household's data
  storage_type      = "gp2"

  db_name  = "money_tracking_app"
  username = "postgres"

  # AWS creates + manages a rotating master-password secret in Secrets
  # Manager automatically -- never touched as plaintext, not even
  # transiently in a .tfvars file. (Yes, this is a small Secrets Manager
  # cost -- see infra/ARCHITECTURE.md; AWS doesn't offer an SSM-backed
  # equivalent for this specific feature, so this is the one place in the
  # whole deployment that still uses Secrets Manager.)
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  multi_az            = false
  storage_encrypted   = true
  skip_final_snapshot = true # personal project, not worth the extra teardown friction/cost of a final snapshot

  # Automated backups -- explicitly set rather than left on whatever the
  # provider default is (confirmed at implementation time: the default
  # is actually 0, backups fully OFF, not something safe to leave
  # implicit for a database holding real financial data).
  #
  # 7 was the original intent, but this specific AWS account rejected it
  # with FreeTierRestrictionError ("exceeds the maximum available to
  # free tier customers") -- likely tied to whatever promotional/credit
  # account cohort this ~2-week-old account is on, not the generic
  # documented RDS free tier (which normally allows up to 35 days).
  # 1 day is the safe fallback: still real backup coverage, accepted by
  # this account's restriction. Revisit once the account ages out of
  # whatever tier is imposing this cap.
  backup_retention_period = 1

  tags = { Name = "${var.name_prefix}-postgres" }
}
