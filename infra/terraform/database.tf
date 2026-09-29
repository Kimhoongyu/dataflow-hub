resource "ncloud_postgresql" "main" {
  service_name       = "tf-dataflow-db"
  server_name_prefix = "tf-pg"
  vpc_no             = data.ncloud_vpc.main.id
  subnet_no          = ncloud_subnet.private_b.id
  user_name          = "dataflow"
  user_password      = var.db_password
  database_name      = "dataflow_hub"
  client_cidr        = ncloud_subnet.private_a.subnet

  ha                           = false # 이중화(대기 서버) 여부
  backup                       = true
  backup_file_retention_period = 7 # 백업 보관 일수 (1~30)
}