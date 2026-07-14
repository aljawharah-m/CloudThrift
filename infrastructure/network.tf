resource "azurerm_virtual_network" "cloudthrift" {
  name                = "${local.name_prefix}-vnet"
  location            = azurerm_resource_group.cloudthrift.location
  resource_group_name = azurerm_resource_group.cloudthrift.name
  address_space       = ["10.20.0.0/16"]

  tags = local.common_tags
}

resource "azurerm_subnet" "application" {
  name                 = "application-subnet"
  resource_group_name  = azurerm_resource_group.cloudthrift.name
  virtual_network_name = azurerm_virtual_network.cloudthrift.name
  address_prefixes     = ["10.20.1.0/24"]
}

resource "azurerm_public_ip" "load_balancer" {
  name                = "${local.name_prefix}-lb-pip"
  location            = azurerm_resource_group.cloudthrift.location
  resource_group_name = azurerm_resource_group.cloudthrift.name

  allocation_method = "Static"
  sku               = "Standard"
  zones             = ["1", "2", "3"]

  tags = local.common_tags
}