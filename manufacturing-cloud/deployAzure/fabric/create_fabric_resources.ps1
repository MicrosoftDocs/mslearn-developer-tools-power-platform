# Pass in the Fabric workspace name as input parameter
#
# Usage
#	$workspaceName="XXX"
#

param (
	[string]$workspaceName
)
$VerbosePreference = "Continue"

$ErrorActionPreference = 'Stop'
$baseFabricUrl = "https://api.fabric.microsoft.com"
$accessToken = (az account get-access-token --resource $baseFabricUrl | ConvertFrom-Json).accessToken
$baseFabricUrl += "/v1"

# Call verify_workspace script to get workspace id
$workspaceId = & "$PSScriptRoot\verify_workspace.ps1" -workspaceName $workspaceName -accessToken $accessToken -baseFabricUrl $baseFabricUrl $VerbosePreference

# Replace spaces and special characters in workspace name with underscores
$modifiedWorkspaceName = $workspaceName -replace "[^a-zA-Z0-9]", "_"

Write-Verbose "modifiedWorkspaceName: $modifiedWorkspaceName"

# Call create_lakehouse script to create lakehouse
$lakeHouseName = "mds_lakehouse_" + $modifiedWorkspaceName
& "$PSScriptRoot\create_lakehouse.ps1" -workspaceId $workspaceId -accessToken $accessToken -baseFabricUrl $baseFabricUrl -lakeHouseName $lakeHouseName $VerbosePreference
Write-Host "Lakehouse with name '$lakeHouseName' exists/created successfully."

# Call create_eventstream script to create eventstreams
$eventStreams = @(
				$("mds_eventstream_" + $modifiedWorkspaceName), 
				$("mds_opcuametadata_" + $modifiedWorkspaceName), 
				$("mds_opcuadata_" + $modifiedWorkspaceName))
				
$streamEventStreamId = & "$PSScriptRoot\create_eventstream.ps1" -workspaceId $workspaceId -accessToken $accessToken -baseFabricUrl $baseFabricUrl -eventStreamName $eventStreams[0] $VerbosePreference
$opcuametaEventStreamId = & "$PSScriptRoot\create_eventstream.ps1" -workspaceId $workspaceId -accessToken $accessToken -baseFabricUrl $baseFabricUrl -eventStreamName $eventStreams[1] $VerbosePreference
$opcuadataEventStreamId = & "$PSScriptRoot\create_eventstream.ps1" -workspaceId $workspaceId -accessToken $accessToken -baseFabricUrl $baseFabricUrl -eventStreamName $eventStreams[2] $VerbosePreference

Write-Host "EventStreams with names '$($eventStreams -join "', '")' exists/created successfully."

# get_connection_string.ps1	to get the connection string for all three eventstreams
$streamConnectionString = & "$PSScriptRoot\get_connection_string.ps1" -workspaceId $workspaceId -eventStreamId $streamEventStreamId -accessToken $accessToken -baseFabricUrl $baseFabricUrl $VerbosePreference
$opcuametaConnectionString = & "$PSScriptRoot\get_connection_string.ps1" -workspaceId $workspaceId -eventStreamId $opcuametaEventStreamId -accessToken $accessToken -baseFabricUrl $baseFabricUrl $VerbosePreference
$opcuadataConnectionString = & "$PSScriptRoot\get_connection_string.ps1" -workspaceId $workspaceId -eventStreamId $opcuadataEventStreamId -accessToken $accessToken -baseFabricUrl $baseFabricUrl $VerbosePreference

Write-Host "Connection strings fetched successfully."

# Return the connection strings as an object
return @{
	StreamConnectionString = $streamConnectionString
	OPCUAMetadataConnectionString = $opcuametaConnectionString
	OPCUADataConnectionString = $opcuadataConnectionString
	LakehouseName = $lakeHouseName
	EventStream = $eventStreams[0]
	OpcuaMetaDataStream = $eventStreams[1]
	OpcuaDataStream = $eventStreams[2]
}