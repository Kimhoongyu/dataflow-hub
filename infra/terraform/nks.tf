# KVM용 NKS 이미지 조회
data "ncloud_nks_server_images" "ubuntu" {
  hypervisor_code = "KVM"

  filter {
    name   = "label"
    values = ["ubuntu-24.04-nksw"]
    regex  = false
  }
}

/*
# 위 이미지에 맞는 노드 스펙 조회
data "ncloud_nks_server_products" "node" {
  software_code = data.ncloud_nks_server_images.rocky.images[0].value
  zone          = "KR-1"

  filter {
    name   = "cpu_count"
    values = ["2"]
  }

  filter {
    name   = "memory_size"
    values = ["4GB"]
  }
}
*/

#NKS 클러스터 생성
resource "ncloud_nks_cluster" "main" {
  name                = "tf-nks-cluster"
  hypervisor_code     = "KVM"
  cluster_type        = "SVR.VNKS.STAND.C002.M004.G003"
  login_key_name      = "test"
  kube_network_plugin = "cilium"
  k8s_version         = "1.34.3-nks.2"

  vpc_no = data.ncloud_vpc.main.id

  subnet_no_list = [
    ncloud_subnet.private_a.id
  ]

  lb_public_subnet_no  = ncloud_subnet.lb_public.id
  lb_private_subnet_no = ncloud_subnet.lb_private.id

  zone = "KR-1"

  log {
    audit = false
  }
}

#노드풀
resource "ncloud_nks_node_pool" "main" {
  cluster_uuid     = ncloud_nks_cluster.main.uuid
  node_pool_name   = "tf-nodepool"
  node_count       = 1
  server_spec_code = "s2-g3a"
  software_code    = data.ncloud_nks_server_images.ubuntu.images[0].value
  storage_size     = 50

  subnet_no_list = [
    ncloud_subnet.private_a.id
  ]
}
