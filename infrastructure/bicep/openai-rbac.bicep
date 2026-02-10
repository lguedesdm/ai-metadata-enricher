// =====================================================
// Azure OpenAI RBAC — Cognitive Services OpenAI User
// =====================================================
// Scope: Assign "Cognitive Services OpenAI User" role to
//        the Orchestrator Managed Identity on the Azure
//        OpenAI resource.
//
// Security guarantees:
//   - Data-plane RBAC only (no management-plane)
//   - Resource-scoped (not subscription-level)
//   - Least-privilege: invoke completions only
//   - No API keys, secrets, or connection strings
//
// Prerequisites:
//   - Azure OpenAI resource must exist
//   - Orchestrator Container App must be deployed with
//     System-Assigned Managed Identity enabled
//   - principalId must be captured from the Container App
//
// Deploy:
//   az deployment group create \
//     --resource-group rg-ai-metadata-dev \
//     --template-file openai-rbac.bicep \
//     --parameters \
//       openaiAccountName=oai-ai-metadata-dev \
//       principalId=<container-app-managed-identity-principal-id>
//
// Role Reference:
//   Cognitive Services OpenAI User:
//     ID: 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd
//     Permissions: Create completions, embeddings, image generations
//     Does NOT include: model deployments, fine-tuning, management

targetScope = 'resourceGroup'

// =====================================================
// Parameters
// =====================================================

@description('Name of the existing Azure OpenAI resource.')
param openaiAccountName string = 'oai-ai-metadata-dev'

@description('Principal ID of the Orchestrator System-Assigned Managed Identity.')
param principalId string

@description('Environment identifier for tagging.')
@allowed(['dev', 'test', 'staging', 'prod'])
param environment string = 'dev'

// =====================================================
// Constants
// =====================================================

// Cognitive Services OpenAI User role definition ID (Azure built-in)
// Docs: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/role-based-access-control
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

// Generate a deterministic GUID for idempotent role assignment
var roleAssignmentId = guid(openaiAccountName, principalId, cognitiveServicesOpenAIUserRoleId)

// =====================================================
// Existing Resources (references only — NO creation)
// =====================================================

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: openaiAccountName
}

// =====================================================
// RBAC Role Assignment — Resource Scope
// =====================================================

resource openaiRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: roleAssignmentId
  scope: openaiAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      cognitiveServicesOpenAIUserRoleId
    )
    principalId: principalId
    principalType: 'ServicePrincipal'
    description: 'Orchestrator MI → Cognitive Services OpenAI User on ${openaiAccountName} (${environment})'
  }
}

// =====================================================
// Outputs
// =====================================================

@description('Role assignment resource ID.')
output roleAssignmentId string = openaiRoleAssignment.id

@description('Azure OpenAI resource ID (for reference).')
output openaiResourceId string = openaiAccount.id
