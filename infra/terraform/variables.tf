variable "region" {
  type    = string
  default = "KR"
}

variable "db_password" {
  type      = string
  sensitive = true
}