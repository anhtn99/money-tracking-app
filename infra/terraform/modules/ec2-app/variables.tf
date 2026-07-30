variable "name_prefix" {
  type = string
}

variable "environment" {
  type        = string
  description = "e.g. \"free-tier\" -- used to scope this instance's SSM parameter read permissions"
}

variable "vpc_id" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "ecr_repository_arn" {
  type = string
}

variable "aws_region" {
  type    = string
  default = "us-east-2"
}

variable "account_id" {
  type = string
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

variable "docker_compose_prod_path" {
  type        = string
  description = "Path to docker-compose.prod.yml, relative to this module or absolute"
}

variable "caddyfile_path" {
  type = string
}
