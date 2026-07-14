output "resource_group_name" {
  description = "CloudThrift resource group name."
  value       = azurerm_resource_group.cloudthrift.name
}

output "location" {
  description = "Azure deployment region."
  value       = azurerm_resource_group.cloudthrift.location
}

output "virtual_network_name" {
  description = "CloudThrift virtual network name."
  value       = azurerm_virtual_network.cloudthrift.name
}

output "subnet_id" {
  description = "Application subnet resource ID."
  value       = azurerm_subnet.application.id
}

output "load_balancer_name" {
  description = "CloudThrift load balancer name."
  value       = azurerm_lb.cloudthrift.name
}

output "public_ip_address" {
  description = "Public IP address used by the CloudThrift load balancer."
  value       = azurerm_public_ip.load_balancer.ip_address
}

output "application_url" {
  description = "Public HTTP endpoint of the CloudThrift workload."
  value       = "http://${azurerm_public_ip.load_balancer.ip_address}"
}

output "health_endpoint" {
  description = "CloudThrift workload health endpoint."
  value       = "http://${azurerm_public_ip.load_balancer.ip_address}/health"
}

output "vm_scale_set_name" {
  description = "CloudThrift VM Scale Set name."
  value       = azurerm_linux_virtual_machine_scale_set.application.name
}

output "vm_scale_set_id" {
  description = "CloudThrift VM Scale Set resource ID."
  value       = azurerm_linux_virtual_machine_scale_set.application.id
}

output "vm_scale_set_identity_principal_id" {
  description = "Managed identity principal ID assigned to the VM Scale Set."
  value       = azurerm_linux_virtual_machine_scale_set.application.identity[0].principal_id
}

output "initial_instance_count" {
  description = "Initial VM Scale Set instance count."
  value       = var.initial_instance_count
}

output "minimum_instance_count" {
  description = "Minimum instance count permitted by CloudThrift."
  value       = var.minimum_instance_count
}

output "maximum_instance_count" {
  description = "Maximum instance count permitted by CloudThrift."
  value       = var.maximum_instance_count
}

output "log_analytics_workspace_name" {
  description = "Log Analytics workspace name."
  value       = azurerm_log_analytics_workspace.cloudthrift.name
}