terraform {
  required_version = ">= 1.10"

  required_providers {
    ncloud = {
      source  = "NaverCloudPlatform/ncloud"
      version = "~> 4.0.7"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }

  # State lives in an NCP Object Storage bucket (S3-compatible). Values come from
  # backend.hcl (see backend.hcl.example): terraform init -backend-config=backend.hcl
  backend "s3" {}
}

# Credentials come from NCLOUD_ACCESS_KEY / NCLOUD_SECRET_KEY, never from files in git.
provider "ncloud" {
  region      = var.region
  support_vpc = true
}
