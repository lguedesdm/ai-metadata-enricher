// ========================================
// Aplicação de TTL em Containers Cosmos DB
// ========================================
// Scope: Aplicar TTL apenas nos containers existentes
// Não altera: account, database, throughput, partition keys, indexing
// Deploy: az deployment group create

targetScope = 'resourceGroup'

// Parâmetros
param cosmosAccountName string = 'cosmos-ai-metadata-dev'
param databaseName string = 'metadata_enricher'

// Referência à conta Cosmos DB existente
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: cosmosAccountName
}

// Referência ao database existente
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' existing = {
  parent: cosmosAccount
  name: databaseName
}

// Container: state
// TTL: 604800 segundos (7 dias)
// Partition Key: /entityType
resource containerState 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'state'
  properties: {
    resource: {
      id: 'state'
      partitionKey: {
        paths: ['/entityType']
        kind: 'Hash'
      }
      defaultTtl: 604800 // 7 dias em segundos
    }
    options: {}
  }
}

// Container: audit
// TTL: 15552000 segundos (180 dias)
// Partition Key: /entityType
resource containerAudit 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'audit'
  properties: {
    resource: {
      id: 'audit'
      partitionKey: {
        paths: ['/entityType']
        kind: 'Hash'
      }
      defaultTtl: 15552000 // 180 dias em segundos
    }
    options: {}
  }
}

// Outputs para validação
output stateContainerName string = containerState.name
output stateTtl int = containerState.properties.resource.defaultTtl
output auditContainerName string = containerAudit.name
output auditTtl int = containerAudit.properties.resource.defaultTtl
