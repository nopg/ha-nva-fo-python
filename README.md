# Azure NVA Route Updater
This Azure Function is used to automatically failover Azure UDR's based on VM Status (running/down)
This allows NVAs (Network Virtual Appliances) such as Meraki MX to be used for failover without needing BGP or other advanced topologies.

This assumes you have one or more UDR's defined to the IP Address of your Primary NVA, and would like it to automatically point to the IP Address of the Secondary NVA if the Primary goes down.

# Route Tables/Route Names
In order to let the Function know which UDR's you would like to modify:

You will need to add a custom Tag to your Route Table, and configure the Name of the tag (tag value doesn't matter)
The UDR's that you would like this Function to control must be named, and each name configured as an environment variable as well.

Nothing will be modified unless the Route Table Tag AND the UDR Name matches what has been configured.

## Authentication / Permissions
To allow the Function access to view VM status and modify existing UDR's we need to authenticate to Azure. It is recommended to assign your Function App a System Assigned Identity (via the Identity section of your Function App). Until someone defines specific permissions to each object, assigning this MSI (Managed System Identity) the Contributor Role to the associated Resource Groups/Subscriptions/NVA's is the best way to allow access. Nothing needs to be added to the code or environment variables for this method to work.

You can also use an App Registration with Client Secrets instead. To use these, create the below environment variables in your Function App:  
AZURE_CLIENT_ID  
AZURE_CLIENT_SECRET  
AZURE_TENANT_ID  

## Required Environment Variables
In order to find the VM's and Route Tables, we also need the subscription(s) in use. Also we need the Resource Group Name(s), and the Primary/Secondary VM names.

| Variable          | Description                               |
| ----------------- | ----------------------------------------- |
| NVA_SUBSCRIPTION  | (Subscription ID that contains the NVA(s)) |
| OTHER_SUBSCRIPTIONS | (Only necesssary if other subscriptions are in use for the NVAs/Route Tables) |
| NVA_RESOURCE_GROUPS | (Comma separated list of any Resource Groups associated with the NVA/Route Tables) |
| NVA_PRIMARY         | (Name of Primary NVA) |
| NVA_SECONDARY       | (Name of Secondary NVA) |
| ROUTE_TAG           | (Tag name assigned to the associated Route Table (value doesn't matter)) |
| ROUTE_NAMES         | (Comma separated list with the names of any relevant UDR's that must be updated) |

## Settings
Other settings that may be modified if desired:
| Variable          | Description                               |
| ----------------- | ----------------------------------------- |
| HEARTBEAT         | (How many SECONDS to wait before each status check) If above 60 seconds, it must be divisible by 60 (i.e. in minutes) Default: 30 seconds |
| PREEMPT           | (True or False, Auto fail-back to Primary once it comes back up) Default: False |
| ENABLED           | (True or False) Default: True |


### Other

(Originally came from: https://github.com/Azure/ha-nva-fo, but who wants to look at Powershell?)
