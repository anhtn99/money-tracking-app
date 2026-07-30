/*
Bootstraps the Terraform remote-state backend that every other config in
this repo (shared/, environments/free-tier, environments/full-textbook)
points at. Solves the classic chicken-and-egg problem: Terraform can't
manage the S3 bucket it needs in order to store its own state, so this
one config runs with plain LOCAL state instead, applied once, by hand,
before anything else.

Account-wide and reusable, not project-specific -- named after the
account rather than "money-tracking-app" specifically, since any future
project in this account can share the same bucket under its own state
key (matches the existing account convention of descriptive, not
generic, resource names -- see anhnguyen-expenses-inbound in the sibling
shared-expenses-sheet repo).

Cost note: an S3 bucket holding a few small state files plus a
pay-per-request DynamoDB table used only for lock acquisition/release
rounds to a fraction of a cent per month -- effectively free, but a real
resource, called out explicitly since "touch nothing billable" was an
earlier design goal for this phase.
*/

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-2"
}

resource "aws_s3_bucket" "terraform_state" {
  bucket = "anhnguyen-terraform-state-884135111378"

  # Terraform state files contain resource IDs and, depending on the
  # resource, sometimes sensitive values in plain text (e.g. the Aurora
  # composed connection string in environments/full-textbook) -- prevent
  # a stray `terraform destroy`/console click from deleting the one
  # source of truth for every environment's real infrastructure.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket                  = aws_s3_bucket.terraform_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Terraform 1.5.7 (the version installed locally, confirmed at
# implementation time) predates native S3 conditional-write locking
# (added in 1.10) -- a DynamoDB lock table is the universally-supported
# way to get state locking on this version, so that's what's used here
# rather than assuming a newer feature is available.
resource "aws_dynamodb_table" "terraform_lock" {
  name         = "terraform-state-lock"
  billing_mode = "PAY_PER_REQUEST" # a handful of lock acquire/release requests per apply -- on-demand costs effectively nothing
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}

output "state_bucket_name" {
  value = aws_s3_bucket.terraform_state.bucket
}

output "lock_table_name" {
  value = aws_dynamodb_table.terraform_lock.name
}
