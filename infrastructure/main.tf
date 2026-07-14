resource "azurerm_resource_group" "cloudthrift" {
  name     = "rg-cloudthrift"
  location = var.location

  tags = local.common_tags
}