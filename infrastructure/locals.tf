locals {
  project_name = "cloudthrift"
  name_prefix  = "${local.project_name}-${var.environment}"

  common_tags = {
    project     = "CloudThrift"
    environment = var.environment
    managed_by  = "Terraform"
    workload    = "Autonomous Infrastructure and FinOps"
    repository  = "CloudThrift"
  }
}