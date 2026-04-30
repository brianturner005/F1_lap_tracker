@description('Base name used to derive resource names.')
param baseName string = 'fantasy-f1'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('GitHub repo in the form owner/repo (used to link the Static Web App).')
param githubRepo string = ''

@description('GitHub branch to deploy from.')
param githubBranch string = 'main'

// ---------------------------------------------------------------------------
// Cosmos DB — serverless
// ---------------------------------------------------------------------------

var cosmosAccountName = '${baseName}-cosmos-${uniqueString(resourceGroup().id)}'

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-02-15-preview' = {
  name: cosmosAccountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location, failoverPriority: 0, isZoneRedundant: false }]
    databaseAccountOfferType: 'Standard'
    capabilities: [{ name: 'EnableServerless' }]
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
  }
}

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-02-15-preview' = {
  parent: cosmosAccount
  name: 'fantasy_f1'
  properties: { resource: { id: 'fantasy_f1' } }
}

resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-02-15-preview' = {
  parent: cosmosDatabase
  name: 'data'
  properties: {
    resource: {
      id: 'data'
      partitionKey: { paths: ['/type'], kind: 'Hash' }
    }
  }
}

// ---------------------------------------------------------------------------
// Azure Static Web App (Free tier) + managed Functions
// ---------------------------------------------------------------------------

resource staticWebApp 'Microsoft.Web/staticSites@2023-01-01' = {
  name: '${baseName}-${uniqueString(resourceGroup().id)}'
  location: location
  sku: { name: 'Free', tier: 'Free' }
  properties: {
    repositoryUrl: empty(githubRepo) ? null : 'https://github.com/${githubRepo}'
    branch: githubBranch
    buildProperties: {
      appLocation: '/'
      apiLocation: 'api'
      outputLocation: 'dist'
    }
  }
}

resource staticWebAppSettings 'Microsoft.Web/staticSites/config@2023-01-01' = {
  parent: staticWebApp
  name: 'appsettings'
  properties: {
    COSMOS_CONNECTION_STRING: cosmosAccount.listConnectionStrings().connectionStrings[0].connectionString
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output staticWebAppUrl string = 'https://${staticWebApp.properties.defaultHostname}'
output cosmosAccountName string = cosmosAccount.name
output deploymentToken string = staticWebApp.listSecrets().properties.apiKey
