# KVM is set explicitly everywhere: the provider and data sources default to XEN.

data "ncloud_nks_versions" "kvm" {
  hypervisor_code = "KVM"
  filter {
    name   = "value"
    values = ["^${replace(var.k8s_version_prefix, ".", "\\.")}\\."]
    regex  = true
  }
}

data "ncloud_nks_server_images" "kvm" {
  hypervisor_code = "KVM"
  filter {
    name   = "label"
    values = [var.node_image_label_regex]
    regex  = true
  }
}

data "ncloud_nks_server_products" "node" {
  software_code = data.ncloud_nks_server_images.kvm.images[0].value
  zone          = var.zone
  filter {
    name   = "product_type"
    values = ["STAND"]
  }
  filter {
    name   = "cpu_count"
    values = [var.node_cpu_count]
  }
  filter {
    name   = "memory_size"
    values = [var.node_memory_size]
  }
}

resource "ncloud_login_key" "nodes" {
  key_name = "${var.name}-nodes"
}

resource "ncloud_nks_cluster" "main" {
  name                 = "${var.name}-nks"
  hypervisor_code      = "KVM"
  cluster_type         = var.nks_cluster_type
  k8s_version          = data.ncloud_nks_versions.kvm.versions[0].value
  login_key_name       = ncloud_login_key.nodes.key_name
  vpc_no               = ncloud_vpc.main.vpc_no
  zone                 = var.zone
  subnet_no_list       = [ncloud_subnet.this["nodes"].id]
  lb_private_subnet_no = ncloud_subnet.this["lb_private"].id
  lb_public_subnet_no  = ncloud_subnet.this["lb_public"].id
  kube_network_plugin  = "cilium"
  public_network       = var.nks_public_endpoint

  log {
    audit = true
  }
}

resource "ncloud_nks_node_pool" "default" {
  cluster_uuid     = ncloud_nks_cluster.main.uuid
  node_pool_name   = "${var.name}-default"
  node_count       = var.node_count
  software_code    = data.ncloud_nks_server_images.kvm.images[0].value
  server_spec_code = data.ncloud_nks_server_products.node.products[0].value
  storage_size     = 100
  subnet_no_list   = [ncloud_subnet.this["nodes"].id]

  autoscale {
    enabled = true
    min     = var.node_min
    max     = var.node_max
  }

  lifecycle {
    # The autoscaler changes node_count at runtime.
    ignore_changes = [node_count]
  }
}
