output "database_url_parameter_arn" {
  value = aws_ssm_parameter.database_url.arn
}

output "database_url_parameter_name" {
  value = aws_ssm_parameter.database_url.name
}

output "plaid_client_id_parameter_arn" {
  value = aws_ssm_parameter.plaid_client_id.arn
}

output "plaid_secret_parameter_arn" {
  value = aws_ssm_parameter.plaid_secret.arn
}
