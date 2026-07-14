from azure.identity import DefaultAzureCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.compute import ComputeManagementClient
import os
from azure.mgmt.network.models import (
    PublicIPAddress,
    PublicIPAddressSku
)

from azure.mgmt.compute.models import (
    Disk,
    DiskSku,
    CreationData,
)

SUBSCRIPTION_ID = os.environ["AZURE_SUBSCRIPTION_ID"]

RESOURCE_GROUP = "rg-cloudthrift"

LOCATION = "uaenorth"


TAGS = {
    "environment": "development",
    "cloudthrift_cleanup": "true",
    "createdAt": "2025-01-01T00:00:00Z"
}

credential = DefaultAzureCredential()


network = NetworkManagementClient(
    credential,
    SUBSCRIPTION_ID
)

compute = ComputeManagementClient(
    credential,
    SUBSCRIPTION_ID
)


print("Creating test resources...")


# -------------------------
# Unused Public IP
# -------------------------

ip_name = "cloudthrift-test-unused-ip"


from azure.mgmt.network.models import (
    PublicIPAddress,
    PublicIPAddressSku
)


network.public_ip_addresses.begin_create_or_update(
    RESOURCE_GROUP,
    ip_name,
    PublicIPAddress(
        location=LOCATION,
        sku=PublicIPAddressSku(
            name="Standard"
        ),
        public_ip_allocation_method="Static",
        tags=TAGS,
    )
).result()


print("Created Public IP")


# -------------------------
# Unused NSG
# -------------------------

nsg_name = "cloudthrift-test-unused-nsg"


network.network_security_groups.begin_create_or_update(
    RESOURCE_GROUP,
    nsg_name,
    {
        "location": LOCATION,
        "tags": TAGS
    }
).result()


print("Created NSG")


# -------------------------
# Unused Route Table
# -------------------------

route_name = "cloudthrift-test-unused-route"


network.route_tables.begin_create_or_update(
    RESOURCE_GROUP,
    route_name,
    {
        "location": LOCATION,
        "tags": TAGS
    }
).result()


print("Created Route Table")


# -------------------------
# Unattached Disk
# -------------------------

disk_name = "cloudthrift-test-unused-disk"

from azure.mgmt.compute.models import (
    Disk,
    DiskSku,
    CreationData,
)


compute.disks.begin_create_or_update(
    RESOURCE_GROUP,
    disk_name,
    Disk(
        location=LOCATION,
        sku=DiskSku(
            name="Standard_LRS"
        ),
        disk_size_gb=4,
        creation_data=CreationData(
            create_option="Empty"
        ),
        tags=TAGS,
    )
).result()

print("Created Disk")


print()
print("CloudThrift cleanup lab resources created.")
print("Run:")
print("python resource_optimizer.py")