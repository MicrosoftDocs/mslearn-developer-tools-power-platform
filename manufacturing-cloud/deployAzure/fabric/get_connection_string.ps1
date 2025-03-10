# Pass in the Fabric basefabric url, workspace id, eventstream name, and accesstoken as input parameters,
# and create the eventstream, including the source and destination custom endpoints.
#
# Usage
#	$baseFabricUrl="https://api.fabric.microsoft.com"
#	$workspaceId="XXX"
#	$eventStreamId="XXX"
#	$accessToken="XXX"
#	./create_eventstream.ps1 -baseFabricUrl $baseFabricUrl -workspaceId $workspaceId -eventStreamId $eventStreamId -accessToken $accessToken -verbose
#	
param (
	[string]$baseFabricUrl,
	[string]$workspaceId,
	[string]$eventStreamId,
	[string]$accessToken
)

$headers = @{Authorization = "Bearer $accessToken"}

# Function to decode Base64 payload
function Decode-Payload {
    param (
        [string]$Base64String
    )
    $decodedBytes = [System.Convert]::FromBase64String($Base64String)
    $decodedString = [System.Text.Encoding]::UTF8.GetString($decodedBytes)
    return $decodedString
}

# get destination custom endpoint id
$eventStreamDefinition = Invoke-RestMethod -Uri "$baseFabricUrl/workspaces/$workspaceId/eventstreams/$eventStreamId/getDefinition" -Headers $headers -Method Post
Write-Verbose "EventStream definition:";
Write-Verbose $eventStreamDefinition | Format-List -Property *

$eventStreamPart = $eventStreamDefinition.definition.parts | Where-Object { $_.path -eq "eventstream.json" }
$eventStreamPayloadBase64 = $eventStreamPart.payload
$eventStreamPayloadDecodedString = Decode-Payload($eventStreamPayloadBase64)
Write-Verbose "eventStreamPayloadDecodedString: $eventStreamPayloadDecodedString"

$eventStreamPayloadJSON = $eventStreamPayloadDecodedString | ConvertFrom-Json
$destinationId = $eventStreamPayloadJSON.destinations[0].id
Write-Verbose "destinationId: $destinationId"

# get destination custom endpoint connection string
$success = $false
$primaryConnectionString = ""
while (-not $success) {
    try {
        $connection = Invoke-RestMethod -Uri "$baseFabricUrl/workspaces/$workspaceId/eventstreams/$eventStreamId/destinations/$destinationId/connection" -Headers $headers -Method Get
        $primaryConnectionString = $connection.accessKeys.primaryConnectionString
        $success = $true
    } catch {
        Write-Verbose "Failed to get connection string. Retrying..."
        Start-Sleep -Seconds 5
    }
}

return $primaryConnectionString
