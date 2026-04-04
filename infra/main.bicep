@description('Base name used to derive resource names.')
param baseName string = 'f1tracker'

@description('Azure region for all resources.')
param location string = resourceGroup().location

// ---------------------------------------------------------------------------
// Storage Account — required by Azure Functions
// ---------------------------------------------------------------------------

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: '${replace(baseName, '-', '')}${uniqueString(resourceGroup().id)}sa'
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
  }
}

// ---------------------------------------------------------------------------
// Cosmos DB — serverless, Session consistency
// ---------------------------------------------------------------------------

var cosmosAccountName = 'f1tracker-cosmos-${uniqueString(resourceGroup().id)}'

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-02-15-preview' = {
  name: cosmosAccountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    databaseAccountOfferType: 'Standard'
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
  }
}

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-02-15-preview' = {
  parent: cosmosAccount
  name: 'f1tracker'
  properties: {
    resource: {
      id: 'f1tracker'
    }
    // No throughput — serverless account manages this automatically.
  }
}

resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-02-15-preview' = {
  parent: cosmosDatabase
  name: 'leaderboard'
  properties: {
    resource: {
      id: 'leaderboard'
      partitionKey: {
        paths: [
          '/track_session'
        ]
        kind: 'Hash'
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
        compositeIndexes: [
          [
            {
              path: '/track_session'
              order: 'ascending'
            }
            {
              path: '/lap_time_ms'
              order: 'ascending'
            }
          ]
        ]
      }
    }
  }
}

// ---------------------------------------------------------------------------
// App Service Plan — Basic B1, Linux (dedicated; avoids Dynamic VM quota)
// ---------------------------------------------------------------------------

resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${baseName}-plan'
  location: location
  sku: {
    name: 'B1'
    tier: 'Basic'
  }
  kind: 'linux'
  properties: {
    reserved: true // Required for Linux plans
  }
}

// ---------------------------------------------------------------------------
// Function App
// ---------------------------------------------------------------------------

var storageConnectionString = 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};EndpointSuffix=${environment().suffixes.storage};AccountKey=${storageAccount.listKeys().keys[0].value}'

resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: '${baseName}-func-${uniqueString(resourceGroup().id)}'
  location: location
  kind: 'functionapp,linux'
  properties: {
    serverFarmId: appServicePlan.id
    reserved: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        {
          name: 'WEBSITE_RUN_FROM_PACKAGE'
          value: '1'
        }
        {
          name: 'AzureWebJobsStorage'
          value: storageConnectionString
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'COSMOS_CONNECTION_STRING'
          value: cosmosAccount.listConnectionStrings().connectionStrings[0].connectionString
        }
      ]
      alwaysOn: true   // Required for dedicated (non-consumption) plans
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
    httpsOnly: true
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output functionAppName string = functionApp.name
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output cosmosAccountName string = cosmosAccount.name
