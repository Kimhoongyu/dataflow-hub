# Hand-off to Kubernetes: the ncp overlay reads these two files (both git-ignored).
locals {
  k8s_generated = "${path.module}/../../deploy/k8s/overlays/ncp/generated"
}

resource "local_file" "k8s_config" {
  filename        = "${local.k8s_generated}/config.env"
  file_permission = "0644"
  content         = <<-EOT
    POSTGRES_HOST=${local.db_host}
    POSTGRES_DB=${var.db_name}
    S3_BUCKET=${ncloud_objectstorage_bucket.uploads.bucket_name}
    ALLOWED_ORIGINS=https://${var.domain}
  EOT
}

resource "local_sensitive_file" "k8s_secret" {
  filename        = "${local.k8s_generated}/secret.env"
  file_permission = "0600"
  content         = <<-EOT
    POSTGRES_USER=${var.db_user}
    POSTGRES_PASSWORD=${random_password.db.result}
    S3_ACCESS_KEY=${var.app_storage_access_key}
    S3_SECRET_KEY=${var.app_storage_secret_key}
  EOT
}

output "nks_cluster_uuid" {
  value = ncloud_nks_cluster.main.uuid
}

output "kubeconfig_command" {
  value = "ncp-iam-authenticator create-kubeconfig --region ${var.region} --clusterUuid ${ncloud_nks_cluster.main.uuid} --output kubeconfig.yaml"
}

output "k8s_version" {
  value = ncloud_nks_cluster.main.k8s_version
}

output "db_host" {
  value = local.db_host
}

output "uploads_bucket" {
  value = ncloud_objectstorage_bucket.uploads.bucket_name
}

output "nat_public_ip" {
  description = "Outbound IP of the nodes (for allow-lists elsewhere)."
  value       = ncloud_nat_gateway.main.public_ip
}
