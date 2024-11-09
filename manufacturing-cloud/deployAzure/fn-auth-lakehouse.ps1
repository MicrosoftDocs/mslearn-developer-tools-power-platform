<#
    Adds the system-assigned identity of an Azure function to a Power BI workspace
#>

# Usage: .\fn-auth-lakehouse.ps1 -FunctionAppIdentity "<FunctionAppObjectId>" -WorkspaceName "<OneLakeWorkspace>"
param(
    # The id of the subscription where the function was deployed
    [Parameter(Mandatory=$true, ParameterSetName='FetchFnId_FetchWsId')]
    [Parameter(Mandatory=$true, ParameterSetName='FetchFnId_WithWsId')]
    [string]$SubscriptionId,
    
    # The resrouce group where the function was deployed
    [Parameter(Mandatory=$true, ParameterSetName='FetchFnId_FetchWsId')]
    [Parameter(Mandatory=$true, ParameterSetName='FetchFnId_WithWsId')]
    [string]$ResourceGroupName,
    
    # The name of the function app to modify
    [Parameter(Mandatory=$true, ParameterSetName='FetchFnId_FetchWsId')]
    [Parameter(Mandatory=$true, ParameterSetName='FetchFnId_WithWsId')]
    [string]$FunctionAppName,
    
    # The id of the service principal that should be added to the workspace
    [Parameter(Mandatory=$true, ParameterSetName='WithFnId_FetchWsId')]
    [Parameter(Mandatory=$true, ParameterSetName='WithFnId_WithWsId')]
    [string]$FunctionAppIdentity,
    
    # The name of the workspace to modify
    [Parameter(Mandatory=$true, ParameterSetName='FetchFnId_FetchWsId')]
    [Parameter(Mandatory=$true, ParameterSetName='WithFnId_FetchWsId')]
    [string]$WorkspaceName,
    
    # The id of the workspace to modify
    [Parameter(Mandatory=$true, ParameterSetName='FetchFnId_WithWsId')]
    [Parameter(Mandatory=$true, ParameterSetName='WithFnId_WithWsId')]
    [string]$WorkspaceId,

    # A switch which enables use of the contributor-level Power BI APIs
    [Parameter(Mandatory=$false)]
    [switch]$Contributor,

    # The tenant to log in to for Power BI & Azure
    [Parameter(Mandatory=$false)]
    [string]$TenantId
)

Write-Output "Installing required modules..."

if (-not (Get-Module MicrosoftPowerBIMgmt.Profile -ListAvailable))
{
    # Used for Connect-PowerBIServiceAccount
    Install-Module -Name MicrosoftPowerBIMgmt.Profile -Repository PSGallery -Force
}

if (-not (Get-Module MicrosoftPowerBIMgmt.Workspaces -ListAvailable))
{
    # Used for Get-PowerBIWorkspace, Add-PowerBIWorkspaceUser
    Install-Module -Name MicrosoftPowerBIMgmt.Workspaces -Repository PSGallery -Force
}

if ($PSCmdlet.ParameterSetName -like '*FetchFnId*')
{
    if (-not (Get-Module Az.Accounts -ListAvailable))
    {
        # Used for Connect-AzAccount
        Install-Module -Name Az.Accounts -Repository PSGallery -Force
    }

    if (-not (Get-Module Az.Functions -ListAvailable))
    {
        # Used for *-AzFunctionApp
        Install-Module -Name Az.Functions -Repository PSGallery -Force
    }
}

# For automation, might need additional args such as:
# -ServicePrincipal -CertificateThumbprint $thumbprint -ApplicationId $aadAppId
if ($TenantId) {
    Connect-PowerBIServiceAccount -Tenant $TenantId
} else {
    Connect-PowerBIServiceAccount
}

if ($PSCmdlet.ParameterSetName -like '*FetchFnId*')
{
    # For automation, might need additional args such as:
    # -ServicePrincipal -CertificateThumbprint $thumbprint -ApplicationId $aadAppId
    if ($TenantId) {
        Connect-AzAccount -Subscription $SubscriptionId -Tenant $TenantId
    } else {
        Connect-AzAccount -Subscription $SubscriptionId
    }

    Write-Output "Retrieving function app details..."

    $functionApp = Get-AzFunctionApp -Name $FunctionAppName -ResourceGroupName $ResourceGroupName -WarningAction SilentlyContinue

    if ([string]::IsNullOrWhitespace($functionApp.IdentityPrincipalId))
    {
        Write-Output "Enabling system-assigned identity for function"
        $FunctionAppIdentity = (Update-AzFunctionApp -Name $FunctionAppName -ResourceGroupName $ResourceGroupName -IdentityType SystemAssigned -Force -WarningAction SilentlyContinue).IdentityPrincipalId
    }
    else
    {
        Write-Output "System-assigned identity already enabled for function"
        $FunctionAppIdentity = $functionApp.IdentityPrincipalId
    }
}

if ($PSCmdlet.ParameterSetName -like '*FetchWsId*')
{
    Write-Output "Retrieving function app details..."

    $getWorkspaceArgs = @{
        Name = $WorkspaceName
    }

    if ($Contributor)
    {
        $getWorkspaceArgs.Scope = "Organization"
    }

    $WorkspaceId = (Get-PowerBIWorkspace @getWorkspaceArgs -ErrorAction Stop).Id
}

$addUserArgs = @{
    Id = $WorkspaceId
    AccessRight = "Contributor"
    Identifier = $FunctionAppIdentity
    PrincipalType = "App"
}

if ($Contributor)
{
    $addUserArgs.Scope = "Organization"
}

# Checking for existing users requires higher permissions (e.g. ability to use -Scope Organization) which we don't always have,
# so this will just try to update and then inspect the error to find out if the user has already been added
try
{
    Add-PowerBIWorkspaceUser @addUserArgs -ErrorAction Stop
    Write-Output "Operation completed successfully"
}
catch [Microsoft.Rest.HttpOperationException]
{
    if ($PSItem.Exception.Response.StatusCode -eq [System.Net.HttpStatusCode]::BadRequest)
    {
        $json = ConvertFrom-Json $PSItem.Exception.Response.Content
        if ($json.error.code -eq "AddingAlreadyExistsGroupUserNotSupportedError")
        {
            Write-Output "Principal $($FunctionAppIdentity) is already a user of workspace $workspaceName"
        }
        else
        {
            throw
        }
    }
    else
    {
        throw
    }
}