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
  cluster_type        = "SVR.VNKS.STAND.C002.M008.G003" # NCP가 실제로 만든 타입(M004 요청 → M008 생성)
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

  lifecycle {
    # 클러스터 접근 권한(access_entries)은 콘솔에서 관리한다.
    # 코드에 적으면 NCP 계정 번호가 공개 저장소에 올라가고, 비워 두면 apply 때 권한이 지워져 kubectl이 막힌다.
    ignore_changes = [access_entries]
  }
}

#노드풀
resource "ncloud_nks_node_pool" "main" {
  cluster_uuid     = ncloud_nks_cluster.main.uuid
  node_pool_name   = "tf-nodepool"
  node_count       = 1
  server_spec_code = "s2-g3a"
  software_code    = data.ncloud_nks_server_images.ubuntu.images[0].value
  storage_size     = 100 # NCP 최소 디스크 크기(50 요청 → 100 생성)

  subnet_no_list = [
    ncloud_subnet.private_a.id
  ]
}
