# Pass in the Fabric workspace name as input parameter,
# and return the Fabric workspace ID.
#
# Usage
#   $baseFabricUrl="https://api.fabric.microsoft.com"
#	$workspaceName="XXX"
#	$accessToken="XXX"
#
# Links
#	https://learn.microsoft.com/en-us/rest/api/fabric/articles/using-fabric-apis

param (
	[string]$baseFabricUrl,
	[string]$workspaceName,
	[string]$accessToken
)
$ErrorActionPreference = 'Stop'

Write-Verbose "Fabric Workspace name: $workspaceName"

$workspace_uri = $baseFabricUrl + "/workspaces"
$headers = @{Authorization = "Bearer $accessToken"}

$existingWorkspaces = Invoke-RestMethod -Uri "$workspace_uri" -Headers $headers -Method GET
$workspace = $existingWorkspaces.value | Where-Object { $_.displayName -eq $workspaceName }

if ($workspace) {
	Write-Verbose "Workspace $workspaceName exists with ID: $($workspace.id)"
	return $workspace.id
}
else{
	Write-Error "Error: Workspace $workspaceName does not exist."
	return $false
}