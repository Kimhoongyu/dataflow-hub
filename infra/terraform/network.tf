# One VPC, one zone. Nodes and the database live in private subnets and reach the internet
# through a NAT gateway; only the load balancer subnet is public.
#
#   10.10.1.0/24    nodes           private  GEN
#   10.10.2.0/24    database        private  GEN
#   10.10.10.0/24   nat gateway     public   NATGW
#   10.10.100.0/24  lb (private)    private  LOADB   (required by NKS)
#   10.10.101.0/24  lb (public)     public   LOADB   (ALB for the ingress)

resource "ncloud_vpc" "main" {
  name            = "${var.name}-vpc"
  ipv4_cidr_block = var.vpc_cidr
}

locals {
  subnets = {
    nodes      = { cidr = cidrsubnet(var.vpc_cidr, 8, 1), type = "PRIVATE", usage = "GEN" }
    database   = { cidr = cidrsubnet(var.vpc_cidr, 8, 2), type = "PRIVATE", usage = "GEN" }
    nat        = { cidr = cidrsubnet(var.vpc_cidr, 8, 10), type = "PUBLIC", usage = "NATGW" }
    lb_private = { cidr = cidrsubnet(var.vpc_cidr, 8, 100), type = "PRIVATE", usage = "LOADB" }
    lb_public  = { cidr = cidrsubnet(var.vpc_cidr, 8, 101), type = "PUBLIC", usage = "LOADB" }
  }
}

resource "ncloud_subnet" "this" {
  for_each       = local.subnets
  name           = "${var.name}-${replace(each.key, "_", "-")}"
  vpc_no         = ncloud_vpc.main.vpc_no
  zone           = var.zone
  subnet         = each.value.cidr
  subnet_type    = each.value.type
  usage_type     = each.value.usage
  network_acl_no = ncloud_vpc.main.default_network_acl_no
}

resource "ncloud_nat_gateway" "main" {
  name      = "${var.name}-nat"
  vpc_no    = ncloud_vpc.main.vpc_no
  zone      = var.zone
  subnet_no = ncloud_subnet.this["nat"].id
}

resource "ncloud_route_table" "private" {
  name                  = "${var.name}-private"
  vpc_no                = ncloud_vpc.main.vpc_no
  supported_subnet_type = "PRIVATE"
}

resource "ncloud_route" "private_egress" {
  route_table_no         = ncloud_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  target_type            = "NATGW"
  target_name            = ncloud_nat_gateway.main.name
  target_no              = ncloud_nat_gateway.main.id
}

# Nodes pull images and the DB fetches updates through the NAT gateway.
resource "ncloud_route_table_association" "private" {
  for_each       = toset(["nodes", "database"])
  route_table_no = ncloud_route_table.private.id
  subnet_no      = ncloud_subnet.this[each.key].id
}
