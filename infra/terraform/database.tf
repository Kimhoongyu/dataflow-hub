# NCP password rules: 8–20 characters with letters, digits and a special character, and none
# of ` & + \ " ' / or space. The special set below avoids all of them.
resource "random_password" "db" {
  length           = 20
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 2
  override_special = "!#$%*-_=?@"
}

resource "ncloud_postgresql" "main" {
  service_name       = "${var.name}-db"
  server_name_prefix = "${var.name}-pg"
  vpc_no             = ncloud_vpc.main.vpc_no
  subnet_no          = ncloud_subnet.this["database"].id
  user_name          = var.db_user
  user_password      = random_password.db.result
  database_name      = var.db_name
  # Only the Kubernetes nodes may connect.
  client_cidr = ncloud_subnet.this["nodes"].subnet

  ha                           = var.db_ha
  backup                       = true
  automatic_backup             = true
  backup_file_retention_period = var.db_backup_retention_days
  storage_encryption           = true
}

locals {
  db_host = ncloud_postgresql.main.postgresql_server_list[0].private_domain
}
