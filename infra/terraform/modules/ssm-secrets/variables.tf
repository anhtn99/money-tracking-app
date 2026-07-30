variable "environment" {
  type        = string
  description = "e.g. \"free-tier\" or \"full-textbook\" -- namespaces the parameter path"
}

variable "database_url" {
  type      = string
  sensitive = true
}

variable "plaid_client_id" {
  type      = string
  sensitive = true
}

variable "plaid_secret" {
  type      = string
  sensitive = true
}
