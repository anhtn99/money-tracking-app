variable "name_prefix" {
  type        = string
  description = "Prefix for resource Name tags, e.g. \"money-tracking-app-freetier\""
}

variable "vpc_cidr" {
  type    = string
  default = "10.10.0.0/16"
}
