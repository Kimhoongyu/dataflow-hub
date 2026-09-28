variable "name" {
  description = "Prefix for every resource name (lowercase letters, digits, hyphens)."
  type        = string
  default     = "dataflow"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,14}$", var.name))
    error_message = "3–15 characters: lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "region" {
  type    = string
  default = "KR"
}

variable "zone" {
  type    = string
  default = "KR-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.10.0.0/16"
}

variable "domain" {
  description = "Public host name of the app, e.g. dataflow.example.com. Used for ALLOWED_ORIGINS."
  type        = string
}

# --- NKS ---------------------------------------------------------------------------------

variable "k8s_version_prefix" {
  description = "Kubernetes minor version to pick from the versions NKS offers."
  type        = string
  default     = "1.32"
}

variable "nks_cluster_type" {
  description = "NKS cluster type code for KVM clusters (control plane size)."
  type        = string
  default     = "SVR.VNKS.STAND.C002.M008.G003"
}

variable "node_image_label_regex" {
  type    = string
  default = "ubuntu-22.04"
}

variable "node_cpu_count" {
  type    = string
  default = "2"
}

variable "node_memory_size" {
  type    = string
  default = "8GB"
}

variable "node_count" {
  description = "Initial worker nodes; autoscaling keeps the pool between node_min and node_max."
  type        = number
  default     = 2
}

variable "node_min" {
  type    = number
  default = 2
}

variable "node_max" {
  type    = number
  default = 4
}

variable "nks_public_endpoint" {
  description = "Expose the Kubernetes API endpoint publicly (kubectl from outside the VPC)."
  type        = bool
  default     = true
}

# --- Cloud DB for PostgreSQL ------------------------------------------------------------

variable "db_user" {
  type    = string
  default = "dataflow"
}

variable "db_name" {
  type    = string
  default = "dataflow_hub"
}

variable "db_ha" {
  description = "Standby replica for failover. Off by default to keep a portfolio setup cheap."
  type        = bool
  default     = false
}

variable "db_backup_retention_days" {
  type    = number
  default = 7
}

# --- Object Storage ---------------------------------------------------------------------

variable "app_storage_access_key" {
  description = "Access key the app uses for Object Storage (create a sub-account limited to Object Storage)."
  type        = string
  sensitive   = true
}

variable "app_storage_secret_key" {
  type      = string
  sensitive = true
}
