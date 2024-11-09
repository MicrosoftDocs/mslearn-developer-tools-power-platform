param location string

@secure()
param dataConn string
@secure()
param metaConn string


targetScope = 'resourceGroup'

// unique string to use for all the deployed resources

var unique = toLower(uniqueString(resourceGroup().id))


// splits connection string by semicolon and gets value by key

func getKeyValue(value string, key string) string =>
  substring(first(filter(split(value, ';'), item => startsWith(item, '${key}=')))!, length(key) + 1)

// gets a value, removes prefix, splits by period, and gets first item

func getHostName(value string, key string, prefix string) string =>
  substring(first(split(getKeyValue(value, key), '.'))!, length(prefix))



var ehReceiveIamRole = 'a638d3c7-ab3a-418d-83e6-5f17a39d4fde'
var ehPublishIamRole = '2b629674-e913-4c01-ae53-ef4638d8f975'

var ehReceiveRoleDef = resourceId('Microsoft.Authorization/roleDefinitions', ehReceiveIamRole)
var ehPublishRoleDef = resourceId('Microsoft.Authorization/roleDefinitions', ehPublishIamRole)



resource eventGrid 'Microsoft.EventGrid/namespaces@2024-06-01-preview' = {
  name: 'eg-${unique}'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'Standard'
    capacity: 40
  }
  properties: {
    topicSpacesConfiguration: {
      state: 'Enabled'
    }
  }
}

resource topic 'Microsoft.EventGrid/namespaces/topics@2024-06-01-preview' = {
  name: 'opcua'
  parent: eventGrid
  properties: {
    inputSchema:'CloudEventSchemaV1_0'
  }
}

module mqttUpdate './mqttUpdate.bicep' = {
  name: 'mqttUpdate'
  params: {
    location: location
    gridName: eventGrid.name
    topicId: topic.id
  }
}

resource topicSpace 'Microsoft.EventGrid/namespaces/topicSpaces@2024-06-01-preview' = {
  name: 'opcua'
  parent: eventGrid
  properties: {
    topicTemplates: [
      '#'
    ]
  }
}

resource clientGroup 'Microsoft.EventGrid/namespaces/clientGroups@2024-06-01-preview' = {
  name: 'publishers'
  parent: eventGrid
  properties: {
    query: 'attributes.publisher = "true"'
  }
}

resource permission 'Microsoft.EventGrid/namespaces/permissionBindings@2024-06-01-preview' = {
  name: 'publish'
  parent: eventGrid
  properties: {
    clientGroupName: clientGroup.name
    permission: 'Publisher'
    topicSpaceName: topicSpace.name
  }
}



resource eventHubNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: 'eh-${unique}'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: 40
  }
  properties: {
    disableLocalAuth: true
  }
}

resource eventHub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  name: 'opcua'
  parent: eventHubNamespace
  properties: {
    messageRetentionInDays: 7
  }
}

resource eventHubDataSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid('eh-ds-${unique}')
  scope: eventHubNamespace
  properties: {
    roleDefinitionId: ehPublishRoleDef
    principalId: eventGrid.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource subscription 'Microsoft.EventGrid/namespaces/topics/eventSubscriptions@2024-06-01-preview' = {
  name: 'subscription'
  parent: topic
  properties: {
    eventDeliverySchema: 'CloudEventSchemaV1_0'
    deliveryConfiguration: {
      deliveryMode: 'Push'
      push: {
        deliveryWithResourceIdentity: {
          identity: {
            type: 'SystemAssigned'
          }
          destination: {
            endpointType: 'EventHub'
            properties: {
              resourceId: eventHub.id
            }
          }
        }
      }
    }
  }
  dependsOn: [
    eventHubDataSender
  ]
}



resource streamJob 'Microsoft.StreamAnalytics/streamingjobs@2021-10-01-preview' = {
  name: 'sa-${unique}'
  location: location
  sku: {
    name: 'Standard'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    sku: {
      name: 'Standard'
    }
  }
}

resource eventHubDataReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid('eh-dr-${unique}')
  scope: eventHub
  properties: {
    roleDefinitionId: ehReceiveRoleDef
    principalId: streamJob.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource streamTransform 'Microsoft.StreamAnalytics/streamingjobs/transformations@2021-10-01-preview' = {
  name: 'transform'
  parent: streamJob
  properties: {
    query: loadTextContent('./query.txt')
  }
}

resource streamFunction 'Microsoft.StreamAnalytics/streamingjobs/functions@2021-10-01-preview' = {
  name: 'wrap'
  parent: streamJob
  properties: {
    type: 'Scalar'
    properties: {
      inputs: [
        {
          dataType: 'any'
        }
      ]
      output: {
        dataType: 'record'
      }
      binding: {
        type: 'Microsoft.StreamAnalytics/JavascriptUdf'
        properties: {
          script: loadTextContent('./wrap.js')
        }
      }
    }
  }
}

resource streamInput 'Microsoft.StreamAnalytics/streamingjobs/inputs@2021-10-01-preview' = {
  name: 'input'
  parent: streamJob
  properties: {
    type: 'Stream'
    datasource: {
      type: 'Microsoft.EventHub/EventHub'
      properties: {
        authenticationMode: 'Msi'
        eventHubName: eventHub.name
        serviceBusNamespace: eventHubNamespace.name  
      }
    }
    serialization: {
      type: 'Json'
      properties: {
        encoding: 'UTF8'
      }
    }
  }
  dependsOn: [
    eventHubDataReceiver
  ]
}

var entityPathData = getKeyValue(dataConn, 'EntityPath')
var saKeyValueData = getKeyValue(dataConn, 'SharedAccessKey')
var saKeyFieldData = getKeyValue(dataConn, 'SharedAccessKeyName')
var serviceBusData = getHostName(dataConn, 'Endpoint', 'sb://')

resource streamDataOuput 'Microsoft.StreamAnalytics/streamingjobs/outputs@2021-10-01-preview' = {
  name: 'output-data'
  parent: streamJob
  properties: {
    datasource: {
      type: 'Microsoft.EventHub/EventHub'
      properties: {
        eventHubName: entityPathData
        serviceBusNamespace: serviceBusData
        authenticationMode: 'ConnectionString'
        sharedAccessPolicyKey: saKeyValueData
        sharedAccessPolicyName: saKeyFieldData
      }
    }
    serialization: {
      type: 'Json'
      properties: {
        format: 'Array'
        encoding: 'UTF8'
      }
    }
  }
}

var entityPathMeta = getKeyValue(metaConn, 'EntityPath')
var saKeyValueMeta = getKeyValue(metaConn, 'SharedAccessKey')
var saKeyFieldMeta = getKeyValue(metaConn, 'SharedAccessKeyName')
var serviceBusMeta = getHostName(metaConn, 'Endpoint', 'sb://')

resource streamMetaOuput 'Microsoft.StreamAnalytics/streamingjobs/outputs@2021-10-01-preview' = {
  name: 'output-meta'
  parent: streamJob
  properties: {
    datasource: {
      type: 'Microsoft.EventHub/EventHub'
      properties: {
        eventHubName: entityPathMeta
        serviceBusNamespace: serviceBusMeta
        authenticationMode: 'ConnectionString'
        sharedAccessPolicyKey: saKeyValueMeta
        sharedAccessPolicyName: saKeyFieldMeta
      }
    }
    serialization: {
      type: 'Json'
      properties: {
        format: 'Array'
        encoding: 'UTF8'
      }
    }
  }
}
