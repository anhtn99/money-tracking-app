/*
Minimal networking for the free-tier environment: one VPC, two PUBLIC
subnets (across two AZs), one Internet Gateway. No private subnets, no
NAT Gateway.

Two public subnets, not one, because RDS requires a DB subnet group
spanning at least two AZs even for a single-AZ instance -- that's an RDS
platform requirement, not a design choice made here. The EC2 instance
only ever uses one of them.

No NAT Gateway: the EC2 instance gets its own public IP (an Elastic IP,
see modules/ec2-app) and reaches the internet directly through the
Internet Gateway -- a NAT Gateway exists specifically to give PRIVATE
subnets (no public IP) outbound access, which isn't a need here. This is
the single biggest cost difference vs. modules/network-full, which DOES
need a NAT Gateway because its ECS tasks and Aurora cluster sit in
private subnets by design. See infra/ARCHITECTURE.md for the full
free-tier vs. full-textbook comparison.
*/

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.name_prefix}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name_prefix}-igw" }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "${var.name_prefix}-public-${count.index}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = { Name = "${var.name_prefix}-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
