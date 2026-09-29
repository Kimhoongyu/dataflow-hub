variable "region" {
  type    = string
  default = "KR"
}

variable "db_password" {
  type      = string
  sensitive = true
}

# 앱이 Object Storage에 접근할 때 쓰는 키 (TF_VAR_app_s3_access_key / TF_VAR_app_s3_secret_key)
variable "app_s3_access_key" {
  type      = string
  sensitive = true
}

variable "app_s3_secret_key" {
  type      = string
  sensitive = true
}

# 브라우저가 접속하는 주소. 쓰기 요청(업로드 등)은 이 주소에서 온 것만 허용한다.
# ALB 주소나 도메인이 정해지면 바꾼다. 예) "https://dataflow.example.com"
variable "app_origin" {
  type    = string
  default = "http://localhost:8080"
}
