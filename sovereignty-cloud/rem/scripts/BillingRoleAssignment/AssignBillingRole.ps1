param (
    [Parameter(Mandatory=$true)]
    [string]$billingAccountId,

    [Parameter(Mandatory=$true)]
    [string]$billingProfileId,

    [Parameter(Mandatory=$true)]
    [string]$principalId,

    [string]$invoiceSectionId,
    [string]$customerId
)

$jsonFilePath = "RoleAssignment.json"
$existingJson = Get-Content -Path $jsonFilePath | ConvertFrom-Json
$guid = [guid]::NewGuid().ToString()
$roleAssignmentGuid = $guid
$ROLE_DEFINITION_ID = "30000000-aaaa-bbbb-cccc-100000000002"

if ($invoiceSectionId) 
{
    $existingJson.properties.roleDefinitionId = "/providers/Microsoft.Billing/billingAccounts/$billingAccountId/billingProfiles/$billingProfileId/invoiceSections/invoiceSectionId/billingRoleDefinitions/$ROLE_DEFINITION_ID"
    $existingJson.properties.principalId = $principalId
}

if ($customerId)
{
    $existingJson.properties.roleDefinitionId = "/providers/Microsoft.Billing/billingAccounts/$billingAccountId/billingProfiles/$billingProfileId/customers/$customerId/billingRoleDefinitions/$ROLE_DEFINITION_ID"
    $existingJson.properties.principalId = $principalId
}

$updatedJson = $existingJson | ConvertTo-Json -Depth 10
$accessToken = az account get-access-token --query "accessToken" -o tsv

$apiUrl = $null
if ($invoiceSectionId) 
{
     $apiUrl = "https://management.azure.com/providers/Microsoft.Billing/billingAccounts/$billingAccountId/billingProfiles/$billingProfileId/invoiceSections/$invoiceSectionId/createBillingRoleAssignment`?api-version=2019-10-01-preview"
}
if ($customerId) 
{
     $apiUrl = "https://management.azure.com/providers/Microsoft.Billing/billingAccounts/$billingAccountId/billingProfiles/$billingProfileId/customers/$customerId/createBillingRoleAssignment`?api-version=2019-10-01-preview"
}

try 
{
    $response = Invoke-RestMethod -Uri $apiUrl -Method POST -Headers @{ Authorization = "Bearer $accessToken" } -Body $updatedJson -ContentType "application/json"
    Write-Host "Successfully assigned role definition id $ROLE_DEFINITION_ID to object id: $principalId. Created billing role assignment with id: $response.name"
}
catch {
    Write-Host "An error occurred while assigning role definition id $ROLE_DEFINITION_ID to object id: $principalId."
    Write-Host $_.Exception.Message
}





