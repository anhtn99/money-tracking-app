/*
Wires together the free-tier environment: network, RDS Postgres, the EC2
app instance, SSM-managed app config, and DNS. See
infra/ARCHITECTURE.md for the full design rationale behind every choice
here vs. environments/full-textbook.
*/

data "aws_caller_identity" "current" {}

data "terraform_remote_state" "shared" {
  backend = "s3"
  config = {
    bucket = "anhnguyen-terraform-state-884135111378"
    key    = "shared/terraform.tfstate"
    region = "us-east-2"
  }
}

locals {
  name_prefix = "money-tracking-app-freetier"
  environment = "free-tier"
  domain      = "app.anhnguyen-expenses.com"
}

module "network" {
  source      = "../../modules/network-freetier"
  name_prefix = local.name_prefix
}

module "ec2_app" {
  source = "../../modules/ec2-app"

  name_prefix        = local.name_prefix
  environment        = local.environment
  vpc_id             = module.network.vpc_id
  subnet_id          = module.network.public_subnet_ids[0]
  ecr_repository_arn = data.terraform_remote_state.shared.outputs.ecr_repository_arn
  account_id         = data.aws_caller_identity.current.account_id

  docker_compose_prod_path = "${path.root}/../../../../docker-compose.prod.yml"
  caddyfile_path           = "${path.root}/../../../Caddyfile"
}

module "rds" {
  source = "../../modules/rds-freetier"

  name_prefix           = local.name_prefix
  vpc_id                = module.network.vpc_id
  subnet_ids            = module.network.public_subnet_ids
  app_security_group_id = module.ec2_app.security_group_id
}

# The RDS-managed master password lives in an AWS-managed Secrets
# Manager secret (manage_master_user_password = true on the DB instance)
# -- read here only to compose DATABASE_URL below, never written to a
# plain Terraform output or a .tfvars file. This is the one point in the
# whole deployment that still touches Secrets Manager, because AWS's
# managed-master-password feature doesn't have an SSM-backed equivalent.
data "aws_secretsmanager_secret_version" "rds_master" {
  secret_id = module.rds.master_user_secret_arn
}

locals {
  rds_credentials = jsondecode(data.aws_secretsmanager_secret_version.rds_master.secret_string)
  database_url    = "postgresql://${module.rds.username}:${local.rds_credentials.password}@${module.rds.endpoint}:${module.rds.port}/${module.rds.db_name}"
}

module "secrets" {
  source = "../../modules/ssm-secrets"

  environment     = local.environment
  database_url    = local.database_url
  plaid_client_id = var.plaid_client_id
  plaid_secret    = var.plaid_secret
}

# No Terraform DNS resource here on purpose -- anhnguyen-expenses.com was
# bought directly on Namecheap (Route 53 domain registration was blocked
# for this AWS account when it was new) and its DNS is managed there too,
# not in a Route 53 hosted zone. Terraform has no Namecheap provider
# wired up, so the A record for `local.domain` pointing at
# module.ec2_app.public_ip has to be added by hand in Namecheap's panel
# once this applies -- see infra/scripts/deploy-free-tier.sh's output
# for the exact value to use.
