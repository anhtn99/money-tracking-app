variable "plaid_client_id" {
  type      = string
  sensitive = true
}

variable "plaid_secret" {
  type      = string
  sensitive = true
}

variable "plaid_env" {
  type    = string
  default = "production" # this is the household's real, long-running deployment -- not sandbox
}
