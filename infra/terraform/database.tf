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

  lifecycle {
    # 비밀번호는 바꿀 수 없는 값이라 달라지면 DB를 지우고 다시 만든다(데이터 손실).
    # 환경 변수를 잘못 넣어도 DB가 교체되지 않도록 변경을 무시한다.
    ignore_changes = [user_password]
  }
}

# DB 방화벽(ACG) 규칙.
# DB를 만들면 NCP가 ACG를 자동으로 만들지만, 규칙은 "같은 ACG끼리만 허용"뿐이다.
# client_cidr는 이 ACG에 규칙을 추가해 주지 않아서, 노드에서 DB로 접속하면 시간 초과가 난다.
# 이 리소스는 ACG의 규칙 전체를 덮어쓰므로, 자동으로 만들어진 규칙 4개도 그대로 적어 둔다.
locals {
  db_acg_no = ncloud_postgresql.main.access_control_group_no_list[0]
}

resource "ncloud_access_control_group_rule" "db" {
  access_control_group_no = local.db_acg_no

  # --- NCP가 자동으로 만든 규칙 (지우면 DB 내부 통신이 끊길 수 있음) ---
  inbound {
    protocol                       = "TCP"
    port_range                     = "5432"
    source_access_control_group_no = local.db_acg_no
    description                    = "auto: same ACG postgres"
  }
  inbound {
    protocol                       = "TCP"
    port_range                     = "20021"
    source_access_control_group_no = local.db_acg_no
    description                    = "auto: same ACG management"
  }
  outbound {
    protocol                       = "TCP"
    port_range                     = "5432"
    source_access_control_group_no = local.db_acg_no
    description                    = "auto: same ACG postgres"
  }
  outbound {
    protocol                       = "TCP"
    port_range                     = "20021"
    source_access_control_group_no = local.db_acg_no
    description                    = "auto: same ACG management"
  }

  # --- 추가: NKS 노드 서브넷에서 PostgreSQL 접속 허용 ---
  inbound {
    protocol    = "TCP"
    port_range  = "5432"
    ip_block    = ncloud_subnet.private_a.subnet
    description = "NKS nodes to postgres"
  }
}