terraform {
  required_version = ">= 1.5.0"

  required_providers {
    ncloud = {
      source  = "NaverCloudPlatform/ncloud"
      version = "~> 4.0"
    }
    # 내 PC에 파일을 쓰는 provider (Kubernetes 설정 파일 생성용, k8s_files.tf)
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }

  # state(Terraform 장부)는 NCP Object Storage에 보관 (S3 호환). 키는 AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY 환경 변수.
  backend "s3" {
    bucket = "khgtest"                    # state를 둘 버킷 이름
    key    = "terraform/dataflow.tfstate" # 버킷 안의 파일 경로
    region = "kr-standard"                # NCP Object Storage의 리전 이름

    endpoints = {
      s3 = "https://kr.object.ncloudstorage.com" # NCP 주소로 보냄
    }

    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }
}

provider "ncloud" {
  region      = var.region
  site        = "public"
  support_vpc = true
}
