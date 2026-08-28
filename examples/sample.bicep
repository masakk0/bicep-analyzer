param location string = 'westeurope'
param appName string = 'myapp'

// Virtual Network
resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: '${appName}-vnet'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: ['10.0.0.0/16']
    }
    subnets: [
      {
        name: 'app-subnet'
        properties: {
          addressPrefix: '10.0.1.0/24'
          delegations: [
            {
              name: 'webapp-delegation'
              properties: {
                serviceName: 'Microsoft.Web/serverFarms'
                actions: [
                  'Microsoft.Network/virtualNetworks/subnets/action'
                ]
              }
            }
          ]
        }
      }
      {
        name: 'pe-subnet'
        properties: {
          addressPrefix: '10.0.2.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

// Storage Account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: '${appName}storage'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    publicNetworkAccess: 'Disabled'
  }
}

// Private Endpoint for Storage
resource storagePrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: '${appName}-storage-pe'
  location: location
  properties: {
    subnet: {
      id: '${vnet.id}/subnets/pe-subnet'
    }
    privateLinkServiceConnections: [
      {
        name: 'storage-connection'
        properties: {
          privateLinkServiceId: storageAccount.id
          groupIds: [
            'blob'
            'queue'
          ]
        }
      }
    ]
  }
}

// Private DNS Zones
resource blobZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.blob.core.windows.net'
}
resource queueZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.queue.core.windows.net'
}
resource cogZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.cognitiveservices.azure.com'
}
resource kvZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.vaultcore.azure.net'
}

// VNet links for Private DNS Zones
resource blobLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  name: 'privatelink.blob.core.windows.net/${appName}-vnetlink'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}
resource queueLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  name: 'privatelink.queue.core.windows.net/${appName}-vnetlink'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}
resource cogLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  name: 'privatelink.cognitiveservices.azure.com/${appName}-vnetlink'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}
resource kvLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  name: 'privatelink.vaultcore.azure.net/${appName}-vnetlink'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}

// App Service Plan
resource appServicePlan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: '${appName}-plan'
  location: location
  sku: { name: 'P1v3', tier: 'PremiumV3' }
}

// Function App (enables managed identity and uses an identity-based storage connection)
resource functionApp 'Microsoft.Web/sites@2022-09-01' = {
  name: '${appName}-func'
  location: location
  kind: 'functionapp'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    virtualNetworkSubnetId: '${vnet.id}/subnets/app-subnet'
    siteConfig: {
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storageAccount.name }
        { name: 'AI_ENDPOINT', value: 'https://${appName}-ai.cognitiveservices.azure.com' }
      ]
    }
  }
}

// RBAC: consentire alla MI della Function l'accesso a Blob e Queue
@description('Storage Blob Data Contributor')
var blobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
@description('Storage Queue Data Contributor')
var queueDataContributor = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'

resource funcBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, 'blob', functionApp.identity.principalId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributor)
    principalId: functionApp.identity.principalId
  }
}
resource funcQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, 'queue', functionApp.identity.principalId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueDataContributor)
    principalId: functionApp.identity.principalId
  }
}

// Azure AI Services
resource aiService 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: '${appName}-ai'
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    publicNetworkAccess: 'Disabled'
  }
}

// Private Endpoint for AI Service
resource aiPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: '${appName}-ai-pe'
  location: location
  properties: {
    subnet: {
      id: '${vnet.id}/subnets/pe-subnet'
    }
    privateLinkServiceConnections: [
      {
        name: 'ai-connection'
        properties: {
          privateLinkServiceId: aiService.id
          groupIds: ['account']
        }
      }
    ]
  }
}

// Zone group for AI PE
resource aiPeZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-04-01' = {
  name: '${aiPrivateEndpoint.name}/default'
  properties: {
    privateDnsZoneConfigs: [
      { name: 'cog', properties: { privateDnsZoneId: cogZone.id } }
    ]
  }
}

// Zone group for Storage PE
resource storagePeZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-04-01' = {
  name: '${storagePrivateEndpoint.name}/default'
  properties: {
    privateDnsZoneConfigs: [
      { name: 'blob', properties: { privateDnsZoneId: blobZone.id } }
      { name: 'queue', properties: { privateDnsZoneId: queueZone.id } }
    ]
  }
}

// Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${appName}-kv'
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    publicNetworkAccess: 'Disabled'
  }
}

// Private Endpoint for Key Vault
resource kvPe 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: '${appName}-kv-pe'
  location: location
  properties: {
    subnet: { id: '${vnet.id}/subnets/pe-subnet' }
    privateLinkServiceConnections: [
      {
        name: 'kv-connection'
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: ['vault']
        }
      }
    ]
  }
}

// Zone group for Key Vault PE
resource kvPeZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-04-01' = {
  name: '${kvPe.name}/default'
  properties: {
    privateDnsZoneConfigs: [
      { name: 'vault', properties: { privateDnsZoneId: kvZone.id } }
    ]
  }
}
