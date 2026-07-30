variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "app_security_group_id" {
  type        = string
  description = "The EC2 instance's security group -- the only thing allowed to reach Postgres"
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}
