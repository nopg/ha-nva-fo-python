"""nva route updater"""

import logging
import os
import sys
from dataclasses import dataclass
from distutils.util import strtobool

import azure.functions as func
from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError
from azure.core.polling._poller import LROPoller
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.compute.v2022_03_01.models import InstanceViewStatus, VirtualMachine
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import Route, RouteTable
from azure.mgmt.resource import ResourceManagementClient

app = func.FunctionApp()
VERSION = "0.0.2"


# Environment Variables
MANAGED_IDENTITY_ID = os.getenv("MANAGED_IDENTITY_ID")
NVA_SUBSCRIPTION = os.getenv("NVA_SUBSCRIPTION")
NVA_RESOURCE_GROUPS = os.getenv("NVA_RESOURCE_GROUPS")
OTHER_SUBSCRIPTIONS = os.getenv("OTHER_SUBSCRIPTIONS")
NVA_PRIMARY = os.getenv("NVA_PRIMARY")
NVA_SECONDARY = os.getenv("NVA_SECONDARY")
ROUTE_TAG = os.getenv("ROUTE_TAG")
ROUTE_NAMES = os.getenv("ROUTE_NAMES")
HEARTBEAT = int(os.getenv("HEARTBEAT", "30"))
ENABLED = os.getenv("ENABLED", os.getenv("ENABLE", "True"))

# Check their existence
required_env_vars = {
    "NVA_SUBSCRIPTION": NVA_SUBSCRIPTION,
    "NVA_RESOURCE_GROUPS": NVA_RESOURCE_GROUPS,
    "NVA_PRIMARY": NVA_PRIMARY,
    "NVA_SECONDARY": NVA_SECONDARY,
    "ROUTE_NAMES": ROUTE_NAMES,
    "ROUTE_TAG": ROUTE_TAG,
}
for name, value in required_env_vars.items():
    if not value:
        logging.fatal(f"Error, required Environment Variable '{name}' was not found or is not set.")


# Managed System Identity on Function App or environment variable AZURE_CLIENT_ID
# and/or AZURE_CLIENT_SECRET/ID and AZURE_TENANT_ID (for SP based login)
if MANAGED_IDENTITY_ID:
    CREDENTIALS = DefaultAzureCredential(managed_identity_client_id=MANAGED_IDENTITY_ID)
else:
    CREDENTIALS = DefaultAzureCredential()

# Environment Variables cleanup
ROUTE_NAMES = [r.strip() for r in ROUTE_NAMES.split(",")]
OTHER_SUBSCRIPTIONS = (
    [s.strip() for s in OTHER_SUBSCRIPTIONS.split(",")] if OTHER_SUBSCRIPTIONS else []
)
NVA_RESOURCE_GROUPS = [rg.strip() for rg in NVA_RESOURCE_GROUPS.split(",")]

if NVA_SUBSCRIPTION not in OTHER_SUBSCRIPTIONS:
    OTHER_SUBSCRIPTIONS.append(NVA_SUBSCRIPTION)

try:
    PREEMPT = strtobool(os.getenv("PREEMPT", "False"))
except ValueError:
    PREEMPT = False
try:
    ENABLED = strtobool(os.getenv("ENABLED", "True"))
except ValueError:
    ENABLED = False


# Set Cron Schedule for Timer Trigger
if HEARTBEAT <= 59:
    SCHEDULE = f"*/{HEARTBEAT} * * * * *"
elif HEARTBEAT == 60:
    SCHEDULE = "* * * * * *"
elif HEARTBEAT % 60 != 0:
    logging.warning(
        f"Heartbeat configured for invalid value ({HEARTBEAT}), defaulting to 30 seconds."
    )
    SCHEDULE = "*/30 * * * * *"
else:
    minutes = HEARTBEAT // 60
    if minutes >= 60:
        logging.warning(
            f"Heartbeat configured for invalid value ({HEARTBEAT}), defaulting to 30 seconds."
        )
        SCHEDULE = "*/30 * * * * *"
    else:
        cron_minutes = f"*/{minutes}" if minutes > 0 else "*"
        SCHEDULE = f"* {cron_minutes} * * * *"


@dataclass
class VMDetails:
    subscription_id: str
    resource_group_name: str
    vm_object: VirtualMachine
    vm_instance_statues: list[InstanceViewStatus]
    private_ip: str
    latest_status: str


@dataclass
class RouteDetails:
    subscription_id: str
    resource_group_name: str
    route_table_object: RouteTable
    route_object: Route
    net_client: NetworkManagementClient
    to_update: bool = False
    update_response: LROPoller | None = None

    @property
    def qualified_route_name(self) -> str:
        """Return a nicely formated route name"""
        return f"{self.subscription_id}/{self.route_table_object.name}/{self.route_object.name}"


def get_nva_vms() -> list[VMDetails]:
    """Return VMDetails objects for the meraki devices"""
    compute_client = ComputeManagementClient(
        credential=CREDENTIALS,
        subscription_id=NVA_SUBSCRIPTION,
    )

    net_client = NetworkManagementClient(credential=CREDENTIALS, subscription_id=NVA_SUBSCRIPTION)

    vms = []

    for NVA_RESOURCE_GROUP in NVA_RESOURCE_GROUPS:
        for virtual_machine in compute_client.virtual_machines.list(
            resource_group_name=NVA_RESOURCE_GROUP
        ):
            if virtual_machine.name in (NVA_PRIMARY, NVA_SECONDARY):
                vm = compute_client.virtual_machines.get(
                    resource_group_name=NVA_RESOURCE_GROUP,
                    vm_name=virtual_machine.name,
                    expand="instanceView",
                )

                interfaces = vm.network_profile.network_interfaces
                if len(interfaces) > 1:
                    raise Exception(
                        f"vm {vm.name} has more than one interface, don't know which to pick..."
                    )

                interface = net_client.network_interfaces.get(
                    network_interface_name=interfaces[0].id.split("/")[-1:][0],
                    resource_group_name=NVA_RESOURCE_GROUP,
                )

                vms.append(
                    VMDetails(
                        subscription_id=NVA_SUBSCRIPTION,
                        resource_group_name=NVA_RESOURCE_GROUP,
                        vm_object=vm,
                        vm_instance_statues=vm.instance_view.statuses,
                        private_ip=interface.ip_configurations[0].private_ip_address,
                        latest_status=vm.instance_view.statuses[-1].display_status.lower(),
                    )
                )

    return vms


def get_valid_next_hops(nva_vms: list[VMDetails]) -> list[str]:
    """Return the appropriate next hop based on the mx VMDetails objects"""

    if len(nva_vms) != 2:
        raise Exception(f"should only be two vms, but we have {len(nva_vms)}")

    next_hop_map = {}

    for nva_vm in nva_vms:
        if nva_vm.latest_status == "vm running":
            next_hop_map[nva_vm.vm_object.name] = nva_vm.private_ip

    valid_next_hops = []
    for nva_name in [NVA_PRIMARY, NVA_SECONDARY]:
        nva_ip = next_hop_map.get(nva_name)
        if nva_ip:
            valid_next_hops.append(nva_ip)

    if valid_next_hops:
        return valid_next_hops

    raise Exception("no running vms available, don't know what to do!")


def get_relevant_routes() -> list[RouteDetails]:
    """Get relevant route objects from all subscriptions/resource-groups"""
    relevant_routes: list[RouteDetails] = []

    for subscription in OTHER_SUBSCRIPTIONS:  # noqa
        if not subscription:
            continue

        res_client = ResourceManagementClient(credential=CREDENTIALS, subscription_id=subscription)

        net_client = NetworkManagementClient(credential=CREDENTIALS, subscription_id=subscription)

        for resource_group in res_client.resource_groups.list():
            for route_table in list(
                net_client.route_tables.list(resource_group_name=resource_group.name)
            ):
                if route_table.tags and ROUTE_TAG in route_table.tags:
                    for route_name in ROUTE_NAMES:
                        try:
                            route = net_client.routes.get(
                                resource_group_name=resource_group.name,
                                route_table_name=route_table.name,
                                route_name=route_name,
                            )
                        except ResourceNotFoundError:
                            logging.warning(
                                f"route name `{route_name}` was not found in RT: {route_table.name}"
                            )
                            continue

                        if not route:
                            logging.warning("uh... had route table tagged, but no route?")
                            continue

                        relevant_routes.append(
                            RouteDetails(
                                subscription_id=subscription,
                                resource_group_name=resource_group.name,
                                route_table_object=route_table,
                                route_object=route,
                                net_client=net_client,
                            )
                        )

    return relevant_routes


def update_routes(relevant_routes: list[RouteDetails], valid_next_hops: list[str]) -> None:
    """Update all routes to the target next hop"""
    for relevant_route in relevant_routes:
        if (
            len(valid_next_hops) > 1
            and PREEMPT
            and relevant_route.route_object.next_hop_ip_address != valid_next_hops[0]
        ):
            logging.warning(
                f"{relevant_route.route_table_object.name}/"
                f"{relevant_route.route_object.name}: Preempt enabled, "
                f"failing back to Primary.."
            )
            relevant_route.to_update = True

        elif relevant_route.route_object.next_hop_ip_address in valid_next_hops:
            logging.warning(
                "skipping route update for route table '"
                f"{relevant_route.route_table_object.name}', already is a valid next hop"
            )
            continue

        relevant_route.to_update = True

        relevant_route.update_response = relevant_route.net_client.routes.begin_create_or_update(
            resource_group_name=relevant_route.resource_group_name,
            route_table_name=relevant_route.route_table_object.name,
            route_name=relevant_route.route_object.name,
            route_parameters=Route(
                id=relevant_route.route_object.id,
                name=relevant_route.route_object.name,
                address_prefix=relevant_route.route_object.address_prefix,
                next_hop_type=relevant_route.route_object.next_hop_type,
                next_hop_ip_address=valid_next_hops[0],
            ),
        )

    for relevant_route in relevant_routes:
        if not relevant_route.to_update:
            # no update was made, skip checking for response
            continue

        relevant_route.update_response.wait()

        status = "succeeded"
        if relevant_route.update_response.status().lower() != "succeeded":
            status = "failed"

        logging.warning(f"{status} updating route {relevant_route.qualified_route_name}")


def main():
    """Run Route Updater"""
    if not ENABLED:
        logging.warning("Disabled, skipping..")
        return

    logging.warning("starting...")
    nva_vms = get_nva_vms()

    valid_next_hops = get_valid_next_hops(nva_vms=nva_vms)
    logging.warning(f"got valid next hop -> {valid_next_hops}")

    relevant_routes = get_relevant_routes()
    logging.warning(
        f"got relevant route names -> {[r.qualified_route_name for r in relevant_routes]}"
    )

    update_routes(relevant_routes=relevant_routes, valid_next_hops=valid_next_hops)

    logging.warning("ending...")


@app.schedule(
    schedule=SCHEDULE,
    arg_name="myTimer",
    run_on_startup=False,
    use_monitor=False,
)
def ha_nva_fo(myTimer: func.TimerRequest) -> None:
    """Timer Entry Point"""
    if myTimer.past_due:
        logging.warning("The timer is past due!")

    logging.warning("Timer triggered Route check:")
    logging.warning(f"Version: {VERSION} \t Schedule: {SCHEDULE}")
    main()


if __name__ == "__main__":
    main()
