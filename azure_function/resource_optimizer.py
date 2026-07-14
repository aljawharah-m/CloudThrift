import json
import logging
import os
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest


logger = logging.getLogger("cloudthrift.resource_optimizer")


class ResourceOptimizer:

    def __init__(self) -> None:

        self.subscription_id = os.environ[
            "AZURE_SUBSCRIPTION_ID"
        ]

        self.credential = DefaultAzureCredential()

        self.client = ResourceGraphClient(
            self.credential
        )

        project_root = (
            Path(__file__).resolve().parent.parent
        )

        policy_path = (
            project_root
            / "policies"
            / "cleanup_policy.json"
        )

        with policy_path.open(
            "r",
            encoding="utf-8-sig",
        ) as file:
            self.policy = json.load(file)


    def _run_query(
        self,
        query: str
    ) -> list[dict[str, Any]]:

        request = QueryRequest(
            subscriptions=[
                self.subscription_id
            ],
            query=query,
        )

        response = self.client.resources(
            request
        )

        if not response.data:
            return []

        return list(response.data)



    def detect_unattached_disks(self):

        return self._run_query(
            """
Resources
| where type =~ 'microsoft.compute/disks'
| where properties.managedBy == ''
| project
id,
name,
resourceGroup,
location,
type,
tags,
diskSizeGB=todouble(properties.diskSizeGB),
sku=tostring(sku.name)
"""
        )



    def detect_unassociated_public_ips(self):

        return self._run_query(
            """
Resources
| where type =~ 'microsoft.network/publicipaddresses'
| where properties.ipConfiguration == ''
| project
id,
name,
resourceGroup,
location,
type,
tags,
sku=tostring(sku.name)
"""
        )



    def detect_unused_network_interfaces(self):

        return self._run_query(
            """
Resources
| where type =~ 'microsoft.network/networkinterfaces'
| where properties.virtualMachine == ''
| project
id,
name,
resourceGroup,
location,
type,
tags
"""
        )



    def detect_unused_nsgs(self):

        return self._run_query(
            """
Resources
| where type =~ 'microsoft.network/networksecuritygroups'
| where array_length(properties.networkInterfaces)==0
and array_length(properties.subnets)==0
| project
id,
name,
resourceGroup,
location,
type,
tags
"""
        )



    def detect_unused_route_tables(self):

        return self._run_query(
            """
Resources
| where type =~ 'microsoft.network/routetables'
| where array_length(properties.subnets)==0
| project
id,
name,
resourceGroup,
location,
type,
tags
"""
        )



    def detect_empty_load_balancers(self):

        return self._run_query(
            """
Resources
| where type =~ 'microsoft.network/loadbalancers'
| where array_length(properties.backendAddressPools)==0
| project
id,
name,
resourceGroup,
location,
type,
tags
"""
        )



    def detect_empty_application_gateways(self):

        return self._run_query(
            """
Resources
| where type =~ 'microsoft.network/applicationgateways'
| where array_length(properties.backendAddressPools)==0
| project
id,
name,
resourceGroup,
location,
type,
tags
"""
        )



    def assess(self):

        if not self.policy.get(
            "enabled",
            False
        ):
            return {
                "status":"DISABLED",
                "resources":[],
                "resource_count":0
            }


        resources=[]


        detectors = [
            (
                "detect_unattached_disks",
                "UNATTACHED_DISK"
            ),
            (
                "detect_unassociated_public_ips",
                "UNASSOCIATED_PUBLIC_IP"
            ),
            (
                "detect_unused_network_interfaces",
                "UNUSED_NETWORK_INTERFACE"
            ),
            (
                "detect_unused_nsgs",
                "UNUSED_NETWORK_SECURITY_GROUP"
            ),
            (
                "detect_unused_route_tables",
                "UNUSED_ROUTE_TABLE"
            ),
            (
                "detect_empty_load_balancers",
                "EMPTY_LOAD_BALANCER"
            ),
            (
                "detect_empty_application_gateways",
                "EMPTY_APPLICATION_GATEWAY"
            ),
        ]


        for method_name, waste_type in detectors:

            try:

                if not self.policy.get(
                    "actions",
                    {}
                ).get(
                    method_name,
                    True
                ):
                    continue


                detector = getattr(
                    self,
                    method_name
                )


                for resource in detector():

                    resource[
                        "waste_type"
                    ] = waste_type

                    resources.append(
                        resource
                    )


            except Exception as error:

                logger.exception(
                    "Detection failed: %s",
                    waste_type
                )


        return {
            "status":
                "WASTE_DETECTED"
                if resources
                else "CLEAN",

            "dry_run":
                self.policy.get(
                    "dry_run",
                    True
                ),

            "resource_count":
                len(resources),

            "resources":
                resources
        }



if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO
    )

    optimizer = ResourceOptimizer()

    print(
        json.dumps(
            optimizer.assess(),
            indent=2,
            default=str
        )
    )