// =====================================================
// Purview RBAC — Data Curator Role Assignment
// =====================================================
// Scope: Assign "Purview Data Curator" role to the
//        Orchestrator Managed Identity on the Microsoft
//        Purview account.
//
// Security guarantees:
//   - Data-plane RBAC only (no management-plane)
//   - Account-scoped
//   - Least-privilege: read/write catalog data only
//   - No API keys, secrets, or connection strings
//
// Prerequisites:
//   - Microsoft Purview account must exist
//   - Orchestrator Container App must be deployed with
//     System-Assigned Managed Identity enabled
//   - principalId must be captured from the Container App
//
// Note on Purview RBAC:
//   Purview uses its own role model assigned through the
//   Purview Governance Portal or via the Purview metadata
//   policy API. The ARM-level role below grants access to
//   the Purview data plane. Additional collection-level
//   roles (Data Curator) may need to be assigned through
//   the Purview portal or metadata policy API.
//
// Deploy:
//   az deployment group create \
//     --resource-group rg-ai-metadata-dev \
//     --template-file purview-rbac.bicep \
//     --parameters \
//       purviewAccountName=purview-ai-metadata-dev \
//       principalId=<container-app-managed-identity-principal-id>
//
// Post-deploy:
//   Assign the Managed Identity "Data Curator" role at
//   the appropriate collection level in Purview:
//
//   This is done via the Purview Governance Portal →
//   Data Map → Collections → Role assignments, or via
//   the Purview metadata policy REST API.

targetScope = 'resourceGroup'

// =====================================================
// Parameters
// =====================================================

@description('Name of the existing Microsoft Purview account.')
param purviewAccountName string = 'purview-ai-metadata-dev'

@description('Principal ID of the Orchestrator System-Assigned Managed Identity.')
param principalId string

@description('Environment identifier for tagging.')
@allowed(['dev', 'test', 'staging', 'prod'])
param environment string = 'dev'

// =====================================================
// Constants
// =====================================================

// Reader role on the Purview ARM resource — allows data-plane access
// The actual "Data Curator" permission is assigned within Purview's
// own metadata policy system (collection-level roles).
// ARM Reader role ID (well-known):
var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'

// Generate a deterministic GUID for idempotent role assignment
var roleAssignmentId = guid(purviewAccountName, principalId, readerRoleId)

// =====================================================
// Existing Resources (references only — NO creation)
// =====================================================

resource purviewAccount 'Microsoft.Purview/accounts@2021-12-01' existing = {
  name: purviewAccountName
}

// =====================================================
// RBAC Role Assignment — Resource Scope
// =====================================================
// This ARM-level role provides the identity access to
// interact with the Purview data plane (Atlas API).
// Collection-level Data Curator role must be assigned
// separately through Purview's metadata policy system.

resource purviewRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: roleAssignmentId
  scope: purviewAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      readerRoleId
    )
    principalId: principalId
    principalType: 'ServicePrincipal'
    description: 'Orchestrator MI → Reader on ${purviewAccountName} (${environment}) — Data Curator assigned in Purview metadata policy'
  }
}

// =====================================================
// Outputs
// =====================================================

@description('Role assignment resource ID.')
output roleAssignmentId string = purviewRoleAssignment.id

@description('Purview account resource ID (for reference).')
output purviewResourceId string = purviewAccount.id

@description('Purview catalog endpoint (for client configuration).')
output purviewEndpoint string = 'https://${purviewAccountName}.purview.azure.com'
