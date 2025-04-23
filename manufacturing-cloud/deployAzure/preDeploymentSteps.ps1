# Example usage:
# .\preDeploymentSteps.ps1 -TENANT_ID "Tenant_id" -APP_NAME "MyApp" -RG_NAME "MyResourceGroup" -RG_REGION "MyRegion" -KV_NAME "MyKeyVault" -UMI_NAME "MyUserManagedIdentity" -FABRIC_WORKSPACE_NAME "MyWorkspace" 
param (
    [Parameter(Mandatory=$true)]
    [string]$TENANT_ID,
    [Parameter(Mandatory=$true)]
    [string]$APP_NAME,
    [Parameter(Mandatory=$true)]
    [string]$RG_NAME,
    [Parameter(Mandatory=$true)]
    [string]$RG_REGION,
    [Parameter(Mandatory=$true)]
    [string]$FABRIC_WORKSPACE_NAME,
    [string]$KV_NAME,
    [string]$UMI_NAME,
    [string]$KV_RESOURCE_ID,
    [string]$UMI_RESOURCE_ID,
    [string]$SERVICE_MANAGEMENT_ID
)

$ErrorActionPreference = 'Stop'
$ScriptOutput = @{}
$ScriptOutput.Config = @{}

function Test-AzureName {
    param (
        [string]$name,
        [string]$type
    )

    switch ($type) {
        "subscription" { return $true } # No specific naming rules for subscription IDs
        "resourceGroup" { return $name -match '^[a-zA-Z0-9_\.\(\)\-]{1,90}$' }
        "region" { 
            if ($name -eq "centraluseuap" -or $name -eq "eastus2euap") {
                throw "Region $name is not supported."
            }
            return $true 
        }
        "keyVault" { return $name -match '^[a-zA-Z0-9-]{3,24}$' }
        "userManagedIdentity" { return $name -match '^[a-zA-Z0-9-_]{1,128}$' }
        default { return $false }
    }
}

function Invoke-AzCommand {
    param (
        [string]$Command
    )
    
    # Run the az command
    Invoke-Expression $Command

    # Check exit code and stop if the command failed
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error executing command: $Command" -f Red
        exit 1  # Stop the script if the command fails
    }
}

function Register-Provider {
    param (
        [string]$namespace
    )
    $registrationState = az provider show --namespace $namespace --query "registrationState" -o tsv
    if ($registrationState -ne "Registered") {
        Write-Host "Registering provider namespace: $namespace"
        Invoke-AzCommand 'az provider register --namespace $namespace'

        # Wait until the provider namespace is registered
        do {
            Write-Host "Waiting for provider namespace $namespace to be registered..."
            Start-Sleep -Seconds 10
            $registrationState = az provider show --namespace $namespace --query "registrationState" -o tsv
        } while ($registrationState -ne "Registered")
        Write-Host "Provider namespace $namespace is now registered."
    } else {
        Write-Host "Provider namespace $namespace is already registered."
    }
}

function New-ResourceGroup {
    param (
        [string]$rgName,
        [string]$rgRegion
    )
    $resourceGroup = az group show --name $rgName --query "name" -o tsv
    if ($null -eq $resourceGroup) {
        Write-Host "Resource group $rgName does not exist. Creating now..."
        Invoke-AzCommand 'az group create --name $rgName --location $rgRegion'
        Write-Host "Resource group $rgName created successfully."
    } else {
        Write-Host "Resource group $rgName already exists."
    }
}

function New-KeyVault {
    param (
        [string]$kvName,
        [string]$rgName,
        [string]$rgRegion,
        [string]$keyVaultResourceId
    )
    if ($keyVaultResourceId) {
        Write-Host "Checking if Key Vault with resource ID $keyVaultResourceId exists..."
        $keyVaultUri = az resource show --ids $keyVaultResourceId --query properties.vaultUri -o tsv
        if ($null -eq $keyVaultUri) {
            throw "Key Vault with resource ID $keyVaultResourceId does not exist."
        } else {
            Write-Host "Key Vault with resource ID $keyVaultResourceId exists."
        }
        return $keyVaultUri
    }
    $keyVault = az keyvault show --name $kvName --resource-group $rgName --query "name" -o tsv
    if ($null -eq $keyVault) {
        Write-Host "Key Vault $kvName does not exist. Creating now..."
        Invoke-AzCommand 'az keyvault create --name $kvName --resource-group $rgName --location $rgRegion'
        Write-Host "Key Vault $kvName created successfully."
    } else {
        Write-Host "Key Vault $kvName already exists."
    }
    Write-Host "Retrieving Key Vault URI"
    $keyVaultUri = az keyvault show --name $KV_NAME --resource-group $RG_NAME --query properties.vaultUri -o tsv
    return $keyVaultUri
}

function Create-UserManagedIdentity {
    param (
        [string]$umiName,
        [string]$rgName,
        [string]$rgRegion,
        [string]$umiResourceId
    )
    if ($umiResourceId) {
        Write-Host "Checking if User Managed Identity with resource ID $umiResourceId exists..."
        $umi = az resource show --ids $umiResourceId --query "name" -o tsv
        if ($null -eq $umi) {
            throw "User Managed Identity with resource ID $umiResourceId does not exist."
        } else {
            Write-Host "User Managed Identity with resource ID $umiResourceId exists."
        }
        return $umiResourceId
    }
    $umi = az identity show --name $umiName --resource-group $rgName --query "name" -o tsv
    if ($null -eq $umi) {
        Write-Host "User managed identity $umiName does not exist. Creating now..."
        Invoke-AzCommand 'az identity create --name $umiName --resource-group $rgName --location $rgRegion'
        Write-Host "User managed identity $umiName created successfully."
    } else {
        Write-Host "User managed identity $umiName already exists."
    }
    Write-Host "Generating output for User Assigned Managed Identity"
    $umiResourceId = az identity show --name $UMI_NAME --resource-group $RG_NAME --query id -o tsv
    return $umiResourceId
}

function Set-Role {
    param (
        [string]$role,
        [string]$assignee,
        [string]$scope,
        [string]$assigneePrincipalType = "User"
    )
    Invoke-AzCommand 'az role assignment create --role $role --assignee-object-id $assignee --assignee-principal-type $assigneePrincipalType --scope $scope'
}

function VerifyAKSQuota {
    param (
        [string]$subscriptionId,
        [string]$region,
        [string]$vmSize
    )

    $vmSkus = Invoke-AzCommand 'az vm list-skus --subscription $subscriptionId --location $region --size $vmSize --all --output table'
    if ($vmSkus -match "None") {
        Write-Host "The VM SKU $vmSize is available without restrictions."
    } else {
        throw "The AKS VM SKU $vmSize has restrictions."
    }
}

Write-Host "Starting pre-deployment steps..."

if (-not (Test-AzureName -name $SUBSCRIPTION_ID -type "subscription")) {
    throw "Invalid subscription ID: $SUBSCRIPTION_ID"
}
if (-not (Test-AzureName -name $RG_NAME -type "resourceGroup")) {
    throw "Invalid resource group name: $RG_NAME"
}
if (-not (Test-AzureName -name $RG_REGION -type "region")) {
    throw "Invalid region name: $RG_REGION"
}
if (!($KV_NAME -xor $KV_RESOURCE_ID)) {
    throw "Either KV_NAME or KV_RESOURCE_ID must be present, but not both. Please provide KV_NAME if it's a new key-vault or KV_RESOURCE_ID for an existing key-vault."
}
if (!($UMI_NAME -xor $UMI_RESOURCE_ID)) {
    throw "Either UMI_NAME or UMI_RESOURCE_ID must be present, but not both. Please provide UMI_NAME if it's a new user-managed identity or UMI_RESOURCE_ID for an existing user-managed identity."
}
if (-not $KV_RESOURCE_ID -and -not (Test-AzureName -name $KV_NAME -type "keyVault")) {
    throw "Invalid Key Vault name: $KV_NAME"
}
if (-not $UMI_RESOURCE_ID -and -not (Test-AzureName -name $UMI_NAME -type "userManagedIdentity")) {
    throw "Invalid user managed identity name: $UMI_NAME"
}

Write-Host "Login to tenant"
Invoke-AzCommand "az login --tenant $TENANT_ID"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Login failed. Please check your credentials and try again." -f Red
    exit 1
}
$out = az account show
$TENANT_ID = $out | ConvertFrom-Json | Select-Object -ExpandProperty tenantId
$SUBSCRIPTION_ID = $out | ConvertFrom-Json | Select-Object -ExpandProperty id
$SUBSCRIPTION_NAME = $out | ConvertFrom-Json | Select-Object -ExpandProperty name

Write-Host "Subscription selected is $SUBSCRIPTION_NAME"

$proceed = Read-Host "Do you want to proceed with the pre-deployment steps? (y/n)"
if ($proceed -eq "n") {
    Write-Host "Exiting the script as per user request."
    exit
}

# creating resource group 
New-ResourceGroup -rgName $RG_NAME -rgRegion $RG_REGION

$errors = @()
# Check for AKS Quota
Write-Host "Checking if AKS quota is available"
try {
    VerifyAKSQuota -subscriptionId $SUBSCRIPTION_ID -region $RG_REGION -vmSize "Standard_DS2_v2"
    Write-Host "AKS quota for Standard_DS2_v2 is available"
} catch {
    $errors += "AKS quota check for Standard_DS2_v2 failed: $_"
}

try {
    VerifyAKSQuota -subscriptionId $SUBSCRIPTION_ID -region $RG_REGION -vmSize "Standard_DS3_v2"
    Write-Host "AKS quota for Standard_DS3_v2 is available"
} catch {
    $errors += "AKS quota check for Standard_DS3_v2 failed: $_"
}

# Check for Cosmos DB Quota
Write-Host "Running what-if deployment for Cosmos DB"
try {
    $random = Get-Random -Minimum 1000 -Maximum 9999
    $cosmosAccountName = "cosmos$random"
    Invoke-AzCommand "az deployment group what-if --resource-group $RG_NAME --template-file 'cosmos.bicep' --parameters accountName=$cosmosAccountName location=$RG_REGION isZoneRedundant=true"
    Write-Host "Cosmos quota is available"
} catch {
    $errors += "Cosmos DB quota check failed: $_"
}

# Check for Function App Quota
Write-Host "Running what-if deployment for Function App"
try {
    Invoke-AzCommand "az deployment group what-if --resource-group $RG_NAME --template-file 'fnapp.bicep' --parameters location=$RG_REGION"
    Write-Host "Function app quota is available"
} catch {
    $errors += "Function App quota check failed: $_"
}

# Output results
if ($errors.Count -eq 0) {
    Write-Output "All quota checks completed successfully."
} else {
    Write-Host "Some quota checks failed:" -ForegroundColor Red
    foreach ($error in $errors) {
        Write-Host $error -ForegroundColor Red
    }
    exit 1
}

Write-Host "Registering ManufacturingPlatform feature"
Invoke-AzCommand 'az feature register --subscription $SUBSCRIPTION_ID --namespace Microsoft.ManufacturingPlatform --name DefaultFeature'

Write-Host "Checking if provider is registered..."
Register-Provider -namespace "Microsoft.ManufacturingPlatform"

# Register existing providers
$providerNamespaces = "Microsoft.Kusto,Microsoft.Resources,Microsoft.Authorization,Microsoft.OperationsManagement,Microsoft.Insights,Microsoft.OperationalInsights,Microsoft.Storage,Microsoft.Compute,Microsoft.ContainerService,Microsoft.ContainerRegistry,Microsoft.ContainerInstance,Microsoft.Kubernetes,Microsoft.DocumentDB,Microsoft.Network,Microsoft.ManagedIdentity,Microsoft.GuestConfiguration,Microsoft.Cache,Microsoft.EventHub,Microsoft.CognitiveServices,Microsoft.Web,Microsoft.AppConfiguration,Microsoft.AlertsManagement"
foreach ($namespace in $providerNamespaces.Split(',')) {
    Register-Provider -namespace $namespace
}

# Enable NRG lockdown preview
Write-Host "Enabling NRG lockdown preview"
Invoke-AzCommand 'az feature register --namespace "Microsoft.ContainerService" --name "NRGLockdownPreview"'
Register-Provider -namespace "Microsoft.ContainerService"

$keyVaultUri = New-KeyVault -kvName $KV_NAME -rgName $RG_NAME -rgRegion $RG_REGION -keyVaultResourceId $KV_RESOURCE_ID

$umiResourceId = Create-UserManagedIdentity -umiName $UMI_NAME -rgName $RG_NAME -rgRegion $RG_REGION -umiResourceId $UMI_RESOURCE_ID

Write-Host "Adding Key Vault Secrets Officer role"
$keyVaultId = az keyvault show --name $KV_NAME --resource-group $RG_NAME --query id -o tsv
$userObjectId = az ad signed-in-user show --query id -o tsv
Invoke-AzCommand "az role assignment create --role 'Key Vault Secrets Officer' --assignee $userObjectId --scope $keyVaultId"

Write-Host "Adding Key Vault Secrets User role"
$managedIdentityId = az identity show --resource-group $RG_NAME --name $UMI_NAME --query id -o tsv
$managedIdentityObjectId = az identity show --resource-group $RG_NAME --name $UMI_NAME --query principalId -o tsv
Set-Role -role "Key Vault Secrets User" -assignee $managedIdentityObjectId -scope $keyVaultId -assigneePrincipalType "ServicePrincipal"

Write-Host "Adding Owner role to UMI to itself"
Set-Role -role "Owner" -assignee $managedIdentityObjectId -scope $managedIdentityId -assigneePrincipalType "ServicePrincipal"

# set execution policy 
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

try{
    # call fabric script to create fabric resources
    $fabricOutput = & ".\fabric\create_fabric_resources.ps1" -workspaceName $FABRIC_WORKSPACE_NAME $VerbosePreference

    # create Fabric secrets in KeyVault 
    Write-Host "Creating secrets in Key Vault"

    $secrets = @{
        OPCUADataEventHubConnection = $fabricOutput.OPCUADataConnectionString
        OPCUAMetaDataEventHubConnection = $fabricOutput.OPCUAMetadataConnectionString
        IngestionEventHubConnection = $fabricOutput.StreamConnectionString
    }

    foreach ($secretName in $secrets.Keys) {
        $secretValue = $secrets[$secretName]
        Write-Host "Creating secret $secretName"
        Invoke-AzCommand "az keyvault secret set --vault-name $KV_NAME --name $secretName --value '$secretValue'"
    }
}
catch{
    Write-Host "Error occurred while creating fabric resources: $_" -ForegroundColor Red
    Write-Host "Continuing with the script execution..."
}

Write-Host "Running app registration script"
Connect-AzAccount -Tenant $TENANT_ID
Set-AzContext -SubscriptionId $SUBSCRIPTION_ID

$EntraAppId = & ".\appRegistration.ps1" -mdsServiceAppName $APP_NAME -serviceTreeId $SERVICE_MANAGEMENT_ID -Verbose:$VerbosePreference

Write-Host "Prerequisites verified and completed successfully. Please take note of below outputs!!!"

$umi = New-Object -TypeName PSObject -Property @{
    type = "UserAssigned"
    userAssignedIdentities = @{}
}
$umi.userAssignedIdentities[$umiResourceId] = @{}

$ScriptOutput.Config = [PSCustomObject]@{
    TenantId = $TENANT_ID
    SubscriptionId = $SUBSCRIPTION_ID
    MDSAppName = $APP_NAME
    Region = $RG_REGION
    ResourceGroup = $RG_NAME
    KeyVaultUri = $keyVaultUri
    'Aad Application Id/Entra Application ID' = $EntraAppId
    FabricLakeHouse = $fabricOutput.LakehouseName
    FabricOneLakePath = "$FABRIC_WORKSPACE_NAME/$($fabricOutput.LakehouseName).lakehouse/Files"
    FabricEventStream = $fabricOutput.EventStream
    FabricOpcuaMetaDataStream = $fabricOutput.OpcuaMetaDataStream
    FabricOpcuaDataStream = $fabricOutput.OpcuaDataStream
    'Identity for Solution Center'= $umi
    'Identity for Azure Portal'= $umiResourceId
}

$ScriptOutput | ConvertTo-Json  -Depth 4 | Write-Output