resource "azurerm_lb" "cloudthrift" {
  name                = "${local.name_prefix}-lb"
  location            = azurerm_resource_group.cloudthrift.location
  resource_group_name = azurerm_resource_group.cloudthrift.name
  sku                 = "Standard"

  frontend_ip_configuration {
    name                 = "public-frontend"
    public_ip_address_id = azurerm_public_ip.load_balancer.id
  }

  tags = local.common_tags
}

resource "azurerm_lb_backend_address_pool" "application" {
  name            = "application-backend-pool"
  loadbalancer_id = azurerm_lb.cloudthrift.id
}

resource "azurerm_lb_probe" "http" {
  name                = "http-health-probe"
  loadbalancer_id     = azurerm_lb.cloudthrift.id
  protocol            = "Http"
  port                = 80
  request_path        = "/health"
  interval_in_seconds = 15
  number_of_probes    = 2
}

resource "azurerm_lb_rule" "http" {
  name                           = "http-load-balancing-rule"
  loadbalancer_id                = azurerm_lb.cloudthrift.id
  protocol                       = "Tcp"
  frontend_port                  = 80
  backend_port                   = 80
  frontend_ip_configuration_name = "public-frontend"
  backend_address_pool_ids       = [azurerm_lb_backend_address_pool.application.id]
  probe_id                       = azurerm_lb_probe.http.id
  disable_outbound_snat          = true
  floating_ip_enabled            = false
  idle_timeout_in_minutes        = 4
}

resource "azurerm_lb_outbound_rule" "internet_access" {
  name                    = "internet-outbound-rule"
  loadbalancer_id         = azurerm_lb.cloudthrift.id
  protocol                = "All"
  backend_address_pool_id = azurerm_lb_backend_address_pool.application.id

  allocated_outbound_ports = 1024
  idle_timeout_in_minutes  = 4
  tcp_reset_enabled        = true

  frontend_ip_configuration {
    name = "public-frontend"
  }
}