resource "azurerm_linux_virtual_machine_scale_set" "application" {
  name                = "${local.name_prefix}-vmss"
  location            = azurerm_resource_group.cloudthrift.location
  resource_group_name = azurerm_resource_group.cloudthrift.name

  sku       = var.vm_sku
  instances = var.initial_instance_count

  admin_username                  = var.admin_username
  disable_password_authentication = true
  computer_name_prefix            = "ctvm"
  upgrade_mode                    = "Manual"
  overprovision                   = false
  single_placement_group          = false
  zone_balance                    = true
  zones                           = ["1", "3"]
  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }

  identity {
    type = "SystemAssigned"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  os_disk {
    storage_account_type = "Standard_LRS"
    caching              = "ReadWrite"
    disk_size_gb         = 30
  }

  network_interface {
    name                          = "primary-network-interface"
    primary                       = true
    enable_accelerated_networking = false

    ip_configuration {
      name                                   = "internal-ip-configuration"
      primary                                = true
      subnet_id                              = azurerm_subnet.application.id
      load_balancer_backend_address_pool_ids = [azurerm_lb_backend_address_pool.application.id]
    }
  }

  custom_data = base64encode(file("${path.module}/cloud-init.yaml"))

  boot_diagnostics {
    storage_account_uri = null
  }

  tags = local.common_tags

  lifecycle {
    ignore_changes = [
      instances
    ]

    precondition {
      condition     = var.minimum_instance_count <= var.initial_instance_count
      error_message = "Initial instance count cannot be lower than the minimum instance count."
    }

    precondition {
      condition     = var.maximum_instance_count >= var.initial_instance_count
      error_message = "Initial instance count cannot exceed the maximum instance count."
    }
  }

  depends_on = [
    azurerm_subnet_network_security_group_association.application,
    azurerm_lb_outbound_rule.internet_access
  ]
}