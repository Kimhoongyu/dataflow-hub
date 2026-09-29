output "nks_server_images" {
  value = data.ncloud_nks_server_images.ubuntu.images
}

output "db_host" {
  value = ncloud_postgresql.main.postgresql_server_list[0].private_domain # DB 서버의 내부 주소(도메인)
}

output "uploads_bucket" {
  value = data.ncloud_objectstorage_bucket.uploads.bucket_name # 업로드 버킷 이름
}