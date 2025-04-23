# Pass in the Fabric Base url, workspace id, eventstream name, and accesstoken as input parameters,
# and create the eventstream, including the source and destination custom endpoints.
#
# Usage
#	$baseFabricUrl="https://api.fabric.microsoft.com"
#	$workspaceId="XXX"
#	$eventStreamName="XXX"
#	$accessToken="XXX"
#	./create_eventstream.ps1 -baseFabricUrl $baseFabricUrl -workspaceId $workspaceId -eventStreamName $eventStreamName -accessToken $accessToken -verbose
#	
# Links
#	https://learn.microsoft.com/en-us/rest/api/fabric/articles/using-fabric-apis

param (
    [string]$baseFabricUrl,
	[string]$workspaceId,
	[string]$eventStreamName,
    [string]$accessToken
)

function Get-EventStreamId {
    param (
        [string]$create_eventstream_uri,
        [string]$eventStreamName,
        [hashtable]$headers
    )

    # check if eventstream already exists 
    $response = Invoke-RestMethod -Uri $create_eventstream_uri -Headers $headers -Method Get
    $eventStreams = $response.value

    foreach ($eventStream in $eventStreams) {
        if ($eventStream.displayName -eq $eventStreamName) {
            Write-Verbose "Eventstream with the name '$eventStreamName' exists."
            return $eventStream.id
        }
    }
    return $null
}

$headers = @{Authorization = "Bearer $accessToken"}
$srcCustomEndpointName = $($eventStreamName + "-src-custom-endpoint")
$destCustomEndpointName = $($eventStreamName + "-dest-custom-endpoint")
$streamName = $($eventStreamName + "-stream")
$create_eventstream_uri = "$baseFabricUrl/workspaces/$workspaceId/eventstreams"

Write-Verbose "create_eventstream_uri: $create_eventstream_uri"

$existingEventStreamId = Get-EventStreamId -create_eventstream_uri $create_eventstream_uri -eventStreamName $eventStreamName -headers $headers
if ($existingEventStreamId) {
    return $existingEventStreamId
}

# Function to encode Base64 payload
function Encode-Payload {
    param (
        [string]$Text
    )
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $base64String = [System.Convert]::ToBase64String($bytes)
    return $base64String
}


$eventStreamPayload = @{
    sources = @(
        @{
            name = $srcCustomEndpointName
            type = "CustomEndpoint"
            properties = @{}
        }
    )
    destinations = @(
        @{
            name = $destCustomEndpointName
            type = "CustomEndpoint"
            properties = @{}
            inputNodes = @(
                @{
                    name = $streamName
                }
            )
        }
    )
    streams = @(
        @{
            name = $streamName
            type = "DefaultStream"
            properties = @{}
            inputNodes = @(
                @{
                    name = $srcCustomEndpointName
                }
            )
        }
    )
    operators = @()
    compatibilityLevel = "1.0"
}
$eventStreamPayloadJSON = $eventStreamPayload | ConvertTo-Json -Depth 4
$eventStreamPayloadString = $eventStreamPayloadJSON.ToString()
Write-Verbose "eventStreamPayloadString: $eventStreamPayloadString"

$platformPayload = @{
    schema = "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json"
    metadata = @{
        type = "Eventstream"
        displayName = "platform-" + $eventStreamName
        description = ""
    }
    config = @{
        version = "2.0"
        logicalId = ""
    }
}
$platformPayloadJSON = $platformPayload | ConvertTo-Json -Depth 4
$platformPayloadString = $platformPayloadJSON.ToString()
Write-Verbose "platformPayloadString: $platformPayloadString"

$eventStreamPayload = Encode-Payload($eventStreamPayloadString)
$platformPayload = Encode-Payload($platformPayloadString)

Write-Verbose "eventStreamPayload: $eventStreamPayload"
Write-Verbose "platformPayload: $platformPayload"

$payload = @{
  displayName = $eventStreamName
  type = "Eventstream"
  definition = @{
    parts = @(
      @{
        path = "eventstream.json"
        payload = $eventStreamPayload
        payloadType = "InlineBase64"
      },
      @{
        path = ".platform"
        payload = $platformPayload
        payloadType = "InlineBase64"
      }
    )
  }
}
$jsonPayload = $payload | ConvertTo-Json -Depth 4
Write-Verbose "payload: $jsonPayload"

$response = Invoke-RestMethod -Uri $create_eventstream_uri -Headers $headers -Method Post -Body $jsonPayload -ContentType "application/json"
if ($response -eq $null) {
    Write-Verbose "No response received from the server."
} else {
    Write-Verbose "Response received: $($response.Id)"
}

# verify eventstream creation
while ($true) {
    Start-Sleep -Seconds 5
    $existingEventStreamId = Get-EventStreamId -create_eventstream_uri $create_eventstream_uri -eventStreamName $eventStreamName -headers $headers
    if ($existingEventStreamId) {
        return $existingEventStreamId
    }
}