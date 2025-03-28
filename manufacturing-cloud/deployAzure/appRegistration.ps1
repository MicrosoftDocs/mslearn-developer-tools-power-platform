Param (
    [Parameter(Mandatory=$true, HelpMessage="The name of the App Registration within Microsoft Entra ID, used by the MDS Service.")]
    [string]$mdsServiceAppName
)

Import-Module Az.Resources

$ErrorActionPreference = 'Stop'
$ScriptOutput = @{}
$ScriptOutput.MDS = @{}
$debuggingIdentifier = ""

function Add-AadApplicationWithServicePrincipal {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DisplayName,
        [Parameter(Mandatory)]
        [string]$ReplyUrls,
        [Parameter(Mandatory)]
        [string]$AppRoles
    )

    Write-Verbose -Message "Creating $($DisplayName)."
    # Converting the `appRoles` JSON to an array of `MicrosoftGraphAppRole` objects.
    $appRolesObject = ConvertFrom-Json -InputObject $AppRoles
    $appRolesObjectCollection = @()
    $appRolesObject.appRoles.ForEach({
        $appRoleJsonString = $_ | ConvertTo-Json
        $appRolesObjectCollection += [Microsoft.Azure.PowerShell.Cmdlets.Resources.MSGraph.Models.ApiV10.MicrosoftGraphAppRole]::FromJsonString($appRoleJsonString)
    })

    # Output matches a manifest file
    $createdApplication = New-AzADApplication `
                            -DisplayName $DisplayName `
                            -ReplyUrls $ReplyUrls `
                            -AvailableToOtherTenants $false `
                            -AppRole $appRolesObjectCollection 

    Write-Verbose -Message "Created application $($createdApplication.appId)."

    Write-Verbose -Message "Adding User.Read permissions to Microsoft Graph for application $($createdApplication.appId)."
    $graphResourceId = "00000003-0000-0000-c000-000000000000"
    $userReadPermission = "e1fe6dd8-ba31-4d61-89e7-88639da4683d"

    Add-AzADAppPermission `
        -ApiId $graphResourceId `
        -PermissionId $userReadPermission `
        -ObjectId $createdApplication.Id

    Write-Verbose -Message "Added User.Read permissions to Microsoft Graph for application $($createdApplication.appId)"
    $enterpriseApplicationDetails = New-AzADServicePrincipal `
                                        -ApplicationId  $createdApplication.AppId

    Write-Information "Created application with Application Id: '$($createdApplication.appId)' (URI = ($($IdentifierUris))) and Enterprise Application object id: '$($enterpriseApplicationDetails.Id)'."

    return @{
        EnterpriseApplicationObjectId   = $enterpriseApplicationDetails.Id
        ApplicationId                   = $createdApplication.appId
        AppRegistrationObjectId         = $createdApplication.Id
    }
}

Function Add-AppRegistrationScopes {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [Guid]$AppRegistrationAppId,
        [Parameter(Mandatory)]
        [Guid]$AppRegistrationObjectId,
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [Microsoft.Azure.PowerShell.Cmdlets.Resources.MSGraph.Models.ApiV10.MicrosoftGraphPermissionScope[]]$Scopes
    )

    $apiApp = New-Object Microsoft.Azure.PowerShell.Cmdlets.Resources.MSGraph.Models.ApiV10.MicrosoftGraphApiApplication
    $apiApp.AcceptMappedClaim = $null
    $apiApp.KnownClientApplication = @()
    $apiApp.PreAuthorizedApplication = @()
    $apiApp.RequestedAccessTokenVersion = $null
    $apiApp.Oauth2PermissionScope = $Scopes

    Update-AzADApplication `
                        -ObjectId $AppRegistrationObjectId `
                        -IdentifierUri "api://$($AppRegistrationAppId)" `
                        -Api $apiApp
}

Function Add-AuthorizedApplicationsToScope {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [Guid]$ApplicationObjectId,
        [Parameter(Mandatory)]
        [Guid[]]$ApplicationIds,
        [Parameter(Mandatory)]
        [Guid[]]$DelegatedPermissionIds
    )

    $preAuthoredAzureCliAppCollection = @()

    $ApplicationIds.ForEach({
        $preAuthoredAzureCliApp = New-Object Microsoft.Azure.PowerShell.Cmdlets.Resources.MSGraph.Models.ApiV10.MicrosoftGraphPreAuthorizedApplication
        $preAuthoredAzureCliApp.AppId = $_
        $preAuthoredAzureCliApp.DelegatedPermissionId = $DelegatedPermissionIds
        $preAuthoredAzureCliAppCollection += $preAuthoredAzureCliApp
    })

    $apiAppWithAuthorizedApps = New-Object Microsoft.Azure.PowerShell.Cmdlets.Resources.MSGraph.Models.ApiV10.MicrosoftGraphApiApplication
    $apiAppWithAuthorizedApps.PreAuthorizedApplication = $preAuthoredAzureCliAppCollection
    Update-AzADApplication `
        -ObjectId $ApplicationObjectId `
        -Api $apiAppWithAuthorizedApps
}

Function Add-MDSApplication {
    $mdsApplicationName = "$($mdsServiceAppName)$($debuggingIdentifier)"
    $mdsApplicationReplyUrl = "https://global.consent.azure-apim.net/redirect"
    $mdsManufacturingUserRoleId = "e332398d-4cf1-4826-9db8-c5f2242b00cc"
    $mdsManufacturingAdminRoleId = "a75e11c3-4233-49ef-93ee-9865d43a9284"
    $mdsApplicationRolesJson = @"
    {
        "appRoles": [
            {
                "allowedMemberTypes": [
                    "User",
                    "Application"
                ],
                "description": "CRUD For Actions, R for KPI",
                "displayName": "Manufacturing User",
                "id": "$($mdsManufacturingUserRoleId)",
                "isEnabled": true,
                "lang": null,
                "origin": "Application",
                "value": "User"
            },
            {
                "allowedMemberTypes": [
                    "User",
                    "Application"
                ],
                "description": "KPI Admin",
                "displayName": "Manufacturing Admin",
                "id": "$($mdsManufacturingAdminRoleId)",
                "isEnabled": true,
                "lang": null,
                "origin": "Application",
                "value": "Admin"
            }
        ]
    }
"@

    $createdMdsApplicationEntepriseApplicationDetails = Add-AadApplicationWithServicePrincipal -DisplayName $mdsApplicationName `
                                                                                            -ReplyUrls $mdsApplicationReplyUrl `
                                                                                            -AppRoles $mdsApplicationRolesJson

    $userScopeId = "c6901f2d-40bd-4d39-bc1c-da543f779266"
    $adminScopeId = "654baecf-978e-48ae-9bf8-6d847cf118c4"
    [Microsoft.Azure.PowerShell.Cmdlets.Resources.MSGraph.Models.ApiV10.MicrosoftGraphPermissionScope]$Oauth2PermissionScopeReadOnly = @{
        AdminConsentDescription = "Read Only"
        AdminConsentDisplayName = "Manufacturing User"
        Id                      = $userScopeId
        IsEnabled               = $true
        Type                    = "User"
        UserConsentDescription  = "Read Only"
        UserConsentDisplayName  = "Manufacturing User"
        Value                   = "ManufacturingUser"
    }
    [Microsoft.Azure.PowerShell.Cmdlets.Resources.MSGraph.Models.ApiV10.MicrosoftGraphPermissionScope]$Oauth2PermissionScopeAdmin = @{
        AdminConsentDescription = "All permissions (CRUD)"
        AdminConsentDisplayName = "Manufacturing Admin"
        Id                      = $adminScopeId
        IsEnabled               = $true
        Type                    = "User"
        UserConsentDescription  = "All permissions (CRUD)"
        UserConsentDisplayName  = "Manufacturing Admin"
        Value                   = "ManufacturingAdmin"
    }

    Add-AppRegistrationScopes `
        -AppRegistrationAppId $createdMdsApplicationEntepriseApplicationDetails.ApplicationId `
        -AppRegistrationObjectId $createdMdsApplicationEntepriseApplicationDetails.AppRegistrationObjectId `
        -Scopes @($Oauth2PermissionScopeReadOnly, $Oauth2PermissionScopeAdmin)

    return @{
        ObjectId                        = $createdMdsApplicationEntepriseApplicationDetails.AppRegistrationObjectId
        ApplicationId                   = $createdMdsApplicationEntepriseApplicationDetails.ApplicationId
        EnterpriseApplicationObjectId   = $createdMdsApplicationEntepriseApplicationDetails.EnterpriseApplicationObjectId
        Scopes                          = @{
            Admin                       = $adminScopeId
            User                        = $userScopeId
        }
        Roles                           = @{
            Admin                       = $mdsManufacturingAdminRoleId
            User                        = $mdsManufacturingUserRoleId
        }
    }
}

$mdsApplicationDetails = Add-MDSApplication

$azureCliAppId = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
$azurePowerShellAppId = "1950a258-227b-4e31-a9cf-717495945fc2"
Add-AuthorizedApplicationsToScope `
        -ApplicationObjectId $mdsApplicationDetails.ObjectId `
        -ApplicationIds $($azureCliAppId, $azurePowerShellAppId) `
        -DelegatedPermissionIds @($mdsApplicationDetails.Scopes.Admin)

$ScriptOutput.MDS.ApplicationId = $mdsApplicationDetails.ApplicationId
$ScriptOutput.MDS.ObjectId = $mdsApplicationDetails.ObjectId
$ScriptOutput.MDS.EnterpriseApplicationObjectId = $mdsApplicationDetails.EnterpriseApplicationObjectId

$ScriptOutput | ConvertTo-Json | Write-Output