#VPC 생성
data "ncloud_vpc" "main" {
  name = "test-vpc"
}

#Subnet 생성
resource "ncloud_subnet" "private_a" {
  vpc_no         = data.ncloud_vpc.main.id
  subnet         = "10.0.10.0/24"
  zone           = "KR-1"
  network_acl_no = data.ncloud_vpc.main.default_network_acl_no
  subnet_type    = "PRIVATE"
  name           = "tf-private-a"
}

resource "ncloud_subnet" "private_b" {
  vpc_no         = data.ncloud_vpc.main.id
  subnet         = "10.0.20.0/24"
  zone           = "KR-1"
  network_acl_no = data.ncloud_vpc.main.default_network_acl_no
  subnet_type    = "PRIVATE"
  name           = "tf-private-b"
}

resource "ncloud_subnet" "lb_public" {
  vpc_no         = data.ncloud_vpc.main.id
  subnet         = "10.0.30.0/24"
  zone           = "KR-1"
  network_acl_no = data.ncloud_vpc.main.default_network_acl_no
  subnet_type    = "PUBLIC"
  usage_type     = "LOADB"
  name           = "tf-lb-public"
}

resource "ncloud_subnet" "lb_private" {
  vpc_no         = data.ncloud_vpc.main.id
  subnet         = "10.0.40.0/24"
  zone           = "KR-1"
  network_acl_no = data.ncloud_vpc.main.default_network_acl_no
  subnet_type    = "PRIVATE"
  usage_type     = "LOADB"
  name           = "tf-lb-private"
}

resource "ncloud_subnet" "nat_gateway" {
  vpc_no         = data.ncloud_vpc.main.id
  subnet         = "10.0.100.0/24"
  zone           = "KR-1"
  network_acl_no = data.ncloud_vpc.main.default_network_acl_no
  subnet_type    = "PUBLIC"
  usage_type     = "NATGW"
  name           = "tf-nat-subnet"
}

#NAT Gateway 생성
resource "ncloud_nat_gateway" "main" {
  vpc_no    = data.ncloud_vpc.main.id
  zone      = "KR-1"
  subnet_no = ncloud_subnet.nat_gateway.id
  name      = "tf-nat"
}

# ② 프라이빗 서브넷용 라우트 테이블
resource "ncloud_route_table" "private" {
  vpc_no                = data.ncloud_vpc.main.id
  supported_subnet_type = "PRIVATE" # 이 테이블을 붙일 서브넷 종류
  name                  = "tf-private-rt"
}

# ② 경로: 모든 외부 트래픽(0.0.0.0/0)은 NAT로
resource "ncloud_route" "to_nat" {
  route_table_no         = ncloud_route_table.private.id # 방금 만든 라우트 테이블
  destination_cidr_block = "0.0.0.0/0"
  target_type            = "NATGW"
  target_no              = ncloud_nat_gateway.main.id   # NAT Gateway의 id
  target_name            = ncloud_nat_gateway.main.name # NAT Gateway의 name
}

# ③ 노드 서브넷에 연결
resource "ncloud_route_table_association" "private_a" {
  route_table_no = ncloud_route_table.private.id
  subnet_no      = ncloud_subnet.private_a.id # 노드가 있는 서브넷
}
