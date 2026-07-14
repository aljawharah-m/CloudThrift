resource "azurerm_log_analytics_workspace" "cloudthrift" {
  name                = "${local.name_prefix}-logs"
  location            = azurerm_resource_group.cloudthrift.location
  resource_group_name = azurerm_resource_group.cloudthrift.name

  sku               = "PerGB2018"
  retention_in_days = 30
  daily_quota_gb    = 0.1

  internet_ingestion_enabled = true
  internet_query_enabled     = true

  tags = local.common_tags
}