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
To allow the Function access to view VM status and modify existing UDR's we need to authenticate to Azure. It is recommended to assign your Function App a User Assigned Identity (via the Identity section of your Function App), disable basic authentication, and create GitHub Federated Credentials (see the section below). The "Easy Button" is to use a System Assigned Identity instead and enable Basic Authention within the Function App. 

For development purposes or other reasons, you can instead use an App Registration with Client Secrets instead. To use these, use the below environment variables in your Function App:  
AZURE_CLIENT_ID  
AZURE_CLIENT_SECRET  
AZURE_TENANT_ID  

Whichever identity is chosen (User/System/Service Principal), the permissions given to it should have Contributor Role 
on any Route Table or NVA involved with this setup. It has only been tested with Subscription level access so far, but feel free to lower the required permissions until it stops working and let me know what you come up with!

## Recommended Authentication Method
- Disable Basic Authentication on the Function App. 
- Assign a User Assigned Identity with appropriate permissions/role assignment.
- Create Federated Credentials on your User Identity, with the below settings:
    | Setting | Value | Notes |
    | ------- | ----- | ----- |
    | Organization | github user or org | if you are unsure, use your username |
    | Repository | repository name | |
    | Entity | Environment | |
    | Environment | Production | always use 'Production' |
    | Name | any_name_you_like | cannot be changed afterwards |


## Required Environment Variables
In order to find the VM's and Route Tables, we also need the subscription(s) in use. Also we need the Resource Group Name(s), and the Primary/Secondary VM names.

| Variable          | Description                               |
| ----------------- | ----------------------------------------- |
| NVA_SUBSCRIPTION  | (Subscription ID that contains the NVA(s)) |
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
| OTHER_SUBSCRIPTIONS | (Only necesssary if other subscriptions are in use for the NVAs/Route Tables) |
| MANAGED_IDENTITY_ID | (only create if NOT using basic-auth, this is the Client ID of your User Managed Identity) |

### Other

Deploy via the Production Deployment Center, slots may or may not work, but are unsupported.

**KNOWN BUG**  (as of June 4, 2024):
When using User Identity and NOT Basic Authentication, Azure currently does not show the Function within
the Function App (See [Azure Functions Bug](https://github.com/Azure/azure-functions-python-worker/issues/1338)). The existing workaround is to modify your GH Actions Workflow file via these steps, AFTER the initial deployment:

1. Inside the "Install dependencies" step of the build job, change the pip install command
```
    pip install --target=".python_packages/lib/site-packages" -r requirements.txt
```
2. Inside the "Zip artifact for deployment" step of the build job, change the zip command so it includes the python_packages
```
    zip release.zip .python_packages ./* -r
```
3. Inside the "Deploy to Azure Functions" step of the deploy job, change these values so it doesn't do a remote build
```
    scm-do-build-during-deployment: false
    enable-oryx-build: false
```

( This originally came from: https://github.com/Azure/ha-nva-fo, but it it didn't work and who wants to look at Powershell?)
