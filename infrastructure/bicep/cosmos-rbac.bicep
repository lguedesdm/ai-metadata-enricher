// =====================================================
// Cosmos DB RBAC — Database-Scoped Data Contributor
// =====================================================
// Scope: Assign Cosmos DB Built-in Data Contributor role
//        to the Orchestrator Managed Identity at the
//        DATABASE scope only.
//
// Security guarantees:
//   - Data-plane RBAC only (no management-plane)
//   - Database-scoped (not account-level)
//   - Least-privilege: read/write data only
//   - No key-based authentication required
//
// Prerequisites:
//   - Cosmos DB account and database must exist
//   - Orchestrator Container App must be deployed with
//     System-Assigned Managed Identity enabled
//   - principalId must be captured from the Container App
//
// Deploy:
//   az deployment group create \
//     --resource-group rg-ai-metadata-dev \
//     --template-file cosmos-rbac.bicep \
//     --parameters \
//       cosmosAccountName=cosmos-ai-metadata-dev \
//       databaseName=metadata_enricher \
//       principalId=<orchestrator-managed-identity-principal-id>
//
// Role Reference:
//   Cosmos DB Built-in Data Contributor:
//     ID: 00000000-0000-0000-0000-000000000002
//     Permissions: Read/write all data, execute queries
//     Does NOT include: management operations, throughput changes,
//                       container creation/deletion, key access

targetScope = 'resourceGroup'

// =====================================================
// Parameters
// =====================================================

@description('Name of the existing Cosmos DB account.')
param cosmosAccountName string = 'cosmos-ai-metadata-dev'

@description('Name of the existing database within the Cosmos DB account.')
param databaseName string = 'metadata_enricher'

@description('Principal ID of the Orchestrator System-Assigned Managed Identity.')
param principalId string

@description('Environment identifier for tagging.')
@allowed(['dev', 'test', 'staging', 'prod'])
param environment string = 'dev'

// =====================================================
// Constants
// =====================================================

// Cosmos DB Built-in Data Contributor role definition ID
// This is a well-known, Azure-defined role for data-plane CRUD operations.
// Documentation: https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-setup-rbac
var dataContributorRoleDefinitionId = '00000000-0000-0000-0000-000000000002'

// Generate a deterministic GUID for the role assignment to ensure idempotency.
// Using principalId + databaseName to scope uniquely per identity + database.
var roleAssignmentId = guid(cosmosAccountName, databaseName, principalId, dataContributorRoleDefinitionId)

// =====================================================
// Existing Resources (references only — NO creation)
// =====================================================

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: cosmosAccountName
}

// =====================================================
// RBAC Role Assignment — Database Scope
// =====================================================
// Assigns at: /subscriptions/.../databaseAccounts/{account}/sqlDatabases/{database}
// This restricts the identity to data operations within this database only.

resource cosmosRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmosAccount
  name: roleAssignmentId
  properties: {
    // Built-in Data Contributor role
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${dataContributorRoleDefinitionId}'

    // Orchestrator Managed Identity
    principalId: principalId

    // Database-level scope (NOT account-level)
    scope: '${cosmosAccount.id}/dbs/${databaseName}'
  }
}

// =====================================================
// Outputs
// =====================================================

@description('The role assignment resource ID.')
output roleAssignmentId string = cosmosRoleAssignment.id

@description('The role definition used (Built-in Data Contributor).')
output roleDefinitionName string = 'Cosmos DB Built-in Data Contributor'

@description('The scope of the role assignment (database-level).')
output roleScope string = '${cosmosAccount.id}/dbs/${databaseName}'

@description('The principal ID that was granted access.')
output assignedPrincipalId string = principalId
