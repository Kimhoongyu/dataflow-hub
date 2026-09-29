# Terraform이 알게 된 값을 Kubernetes(ncp overlay)가 읽는 파일로 넘겨준다.
# 두 파일 모두 .gitignore에 들어 있어 GitHub에 올라가지 않는다.

locals {
  # 이 파일(infra/terraform) 기준으로 두 칸 위 → deploy/k8s/overlays/ncp/generated
  k8s_generated_dir = "${path.module}/../../deploy/k8s/overlays/ncp/generated"
}

# 비밀이 아닌 설정: DB 주소, DB 이름, 버킷 이름, 허용할 접속 주소
resource "local_file" "k8s_config" {
  filename = "${local.k8s_generated_dir}/config.env"
  content  = <<-EOT
    POSTGRES_HOST=${ncloud_postgresql.main.postgresql_server_list[0].private_domain}
    POSTGRES_DB=${ncloud_postgresql.main.database_name}
    S3_BUCKET=${data.ncloud_objectstorage_bucket.uploads.bucket_name}
    ALLOWED_ORIGINS=${var.app_origin}
  EOT
}

# 비밀 값: DB 계정과 저장소 키. local_sensitive_file은 plan 화면에 내용을 보여주지 않는다.
resource "local_sensitive_file" "k8s_secret" {
  filename        = "${local.k8s_generated_dir}/secret.env"
  file_permission = "0600"
  content         = <<-EOT
    POSTGRES_USER=${ncloud_postgresql.main.user_name}
    POSTGRES_PASSWORD=${var.db_password}
    S3_ACCESS_KEY=${var.app_s3_access_key}
    S3_SECRET_KEY=${var.app_s3_secret_key}
  EOT
}
