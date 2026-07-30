output "instance_id" {
  value = module.ec2_app.instance_id
}

output "public_ip" {
  value = module.ec2_app.public_ip
}

output "app_domain" {
  value       = local.domain
  description = "Not auto-created by Terraform -- add an A record for this pointing at `public_ip` in Namecheap's DNS panel"
}

output "rds_endpoint" {
  value = module.rds.endpoint
}
