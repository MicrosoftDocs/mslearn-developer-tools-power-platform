# Pass in the Fabric Base Url, Fabric workspace id, lakehouse name, and accesstoken as input parameters,
# and create the lakehouse
# Usage
#   $baseFabricUrl="https://api.fabric.microsoft.com"
#	$workspaceId="XXX"
#	$lakeHouseName="XXX"
#	$accessToken="XXX"
#	./create_lakehouse.ps1 -baseFabricUrl $baseFabricUrl -workspaceId $workspaceId -lakeHouseName $lakeHouseName -accessToken $accessToken -verbose
#
# Links
#	https://learn.microsoft.com/en-us/rest/api/fabric/articles/using-fabric-apis

param (
    [string]$baseFabricUrl,
	[string]$workspaceId,
	[string]$lakeHouseName,
    [string]$accessToken
)

$create_lakehouse_uri = "$baseFabricUrl/workspaces/$workspaceId/lakehouses"
$headers = @{Authorization = "Bearer $accessToken"}

$response = Invoke-RestMethod -Uri $create_lakehouse_uri -Headers $headers -Method Get
$lakehouses = $response.value

Write-Verbose "create_lakehouse_uri: $create_lakehouse_uri"

foreach ($lakehouse in $lakehouses) {
    if ($lakehouse.displayName -eq $lakeHouseName) {
        Write-Verbose "Lakehouse with the name '$lakeHouseName' already exists."
        exit 0
    }
}

$payload = @{
  displayName = $lakeHouseName
  type = "Lakehouse"
  creationPayload = @{
    enableSchemas = $true
  }
}
$jsonPayload = $payload | ConvertTo-Json -Depth 4

Write-Verbose "payload: $jsonPayload"

$response = Invoke-RestMethod -Uri $create_lakehouse_uri -Headers $headers -Method Post -Body $jsonPayload -ContentType "application/json"
if ($response -eq $null) {
    Write-Verbose "No response received from the server."
} else {
    Write-Verbose "Response received: $($response | ConvertTo-Json -Depth 4)"
}


