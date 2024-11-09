param topicId string

param location string
param gridName string

resource mqttUpdate 'Microsoft.EventGrid/namespaces@2024-06-01-preview' = {
  name: gridName
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
      routeTopicResourceId: topicId
      maximumSessionExpiryInHours: 8
      maximumClientSessionsPerAuthenticationName: 100
    }
  }
}
