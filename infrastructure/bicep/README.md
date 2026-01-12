# Bicep Infrastructure

Azure Bicep templates for deploying the AI Metadata Enricher platform.

## Overview

Bicep is Azure's domain-specific language for deploying resources declaratively. It provides a more concise syntax than ARM templates while maintaining full Azure resource coverage.

## Directory Structure

```
bicep/
├── main.bicep                 # Main orchestration template
├── modules/                   # Reusable Bicep modules
│   ├── storage/              # Storage account modules
│   ├── functions/            # Azure Functions modules
│   ├── cognitive-services/   # AI services modules
│   ├── monitoring/           # Observability modules
│   └── networking/           # Network infrastructure modules
├── environments/             # Environment-specific parameters
│   ├── dev.bicepparam       # Development parameters
│   ├── test.bicepparam      # Test parameters
│   ├── staging.bicepparam   # Staging parameters
│   └── prod.bicepparam      # Production parameters
└── README.md
```

## Prerequisites

- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) (latest version)
- [Bicep CLI](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/install) (installed via Azure CLI)
- Azure subscription with appropriate permissions
- Service principal or user identity for deployments

## Installation

Install Bicep CLI via Azure CLI:

```powershell
az bicep install
```

Upgrade to latest version:

```powershell
az bicep upgrade
```

## Local Development

### Validate Bicep Templates

```powershell
# Validate syntax
az bicep build --file main.bicep

# Check for errors and warnings
az deployment sub validate `
  --location eastus `
  --template-file main.bicep `
  --parameters environments/dev.bicepparam
```

### Preview Changes (What-If)

```powershell
az deployment sub what-if `
  --location eastus `
  --template-file main.bicep `
  --parameters environments/dev.bicepparam
```

### Lint Templates

```powershell
# Bicep linter runs automatically during build
az bicep build --file main.bicep
```

## Deployment

### Deploy to Resource Group

```powershell
# Create resource group
az group create `
  --name rg-ai-enricher-dev-eastus-01 `
  --location eastus

# Deploy infrastructure
az deployment group create `
  --resource-group rg-ai-enricher-dev-eastus-01 `
  --template-file main.bicep `
  --parameters environments/dev.bicepparam
```

### Deploy to Subscription

```powershell
az deployment sub create `
  --location eastus `
  --template-file main.bicep `
  --parameters environments/dev.bicepparam
```

## Module Development

### Creating a Reusable Module

Example module structure (`modules/storage/main.bicep`):

```bicep
@description('Storage account name')
param storageAccountName string

@description('Azure region')
param location string = resourceGroup().location

@description('Storage SKU')
@allowed([
  'Standard_LRS'
  'Standard_GRS'
  'Standard_RAGRS'
])
param skuName string = 'Standard_LRS'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: skuName
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

output storageAccountId string = storageAccount.id
output storageAccountName string = storageAccount.name
```

### Using Modules

```bicep
module storage 'modules/storage/main.bicep' = {
  name: 'storageDeployment'
  params: {
    storageAccountName: 'staienricherprod01'
    location: location
    skuName: 'Standard_GRS'
  }
}
```

## Parameter Files

Use `.bicepparam` files for environment-specific configurations:

```bicep
// environments/dev.bicepparam
using './main.bicep'

param environment = 'dev'
param location = 'eastus'
param appName = 'ai-enricher'
```

## Best Practices

1. **Use Parameters**: Externalize all configurable values
2. **Leverage Modules**: Create reusable, composable modules
3. **Document**: Use `@description` decorators extensively
4. **Validate**: Use `@allowed`, `@minLength`, `@maxLength` constraints
5. **Security**: Reference secrets from Key Vault, never hardcode
6. **Naming**: Follow Azure naming conventions
7. **Outputs**: Expose necessary outputs for dependent deployments
8. **Idempotency**: Ensure templates can be run multiple times safely

## Common Patterns

### Resource Naming

```bicep
var resourceSuffix = '${appName}-${environment}-${location}'
var storageAccountName = 'st${replace(resourceSuffix, '-', '')}'
var functionAppName = 'func-${resourceSuffix}'
```

### Managed Identity (MANDATORY for Production)

**CRITICAL**: All Azure resources MUST use System-Assigned Managed Identity for authentication.

```bicep
resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp'
  identity: {
    type: 'SystemAssigned'  // REQUIRED - enables passwordless authentication
  }
  properties: {
    // ...
  }
}

// Grant Managed Identity access to Storage
resource storageRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storageAccount
  name: guid(storageAccount.id, functionApp.id, 'StorageBlobDataContributor')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}
```

**Benefits**:
- ✅ No connection strings or keys in code
- ✅ Automatic credential rotation
- ✅ Fine-grained RBAC control
- ✅ Audit trail of all access

### Key Vault References

```bicep
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// Reference secret in app settings
appSettings: [
  {
    name: 'ApiKey'
    value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/api-key/)'
  }
]
```

## Troubleshooting

### Common Issues

**Issue**: Deployment fails with "resource already exists"
```powershell
# Use incremental mode (default) or complete mode carefully
--mode Incremental
```

**Issue**: Storage account name invalid
```bicep
// Must be 3-24 characters, lowercase, alphanumeric only
var storageAccountName = toLower(take(replace('st-${uniqueString(resourceGroup().id)}', '-', ''), 24))
```

### Debugging

Enable debug logging:

```powershell
az deployment group create `
  --debug `
  --resource-group rg-ai-enricher-dev `
  --template-file main.bicep `
  --parameters environments/dev.bicepparam
```

## CI/CD Integration

Example GitHub Actions workflow:

```yaml
- name: Deploy Bicep
  uses: azure/arm-deploy@v1
  with:
    subscriptionId: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
    resourceGroupName: rg-ai-enricher-${{ env.ENVIRONMENT }}
    template: ./infrastructure/bicep/main.bicep
    parameters: ./infrastructure/bicep/environments/${{ env.ENVIRONMENT }}.bicepparam
```

## Resources

- [Bicep Documentation](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/)
- [Bicep Examples](https://github.com/Azure/bicep)
- [Azure Resource Reference](https://learn.microsoft.com/en-us/azure/templates/)
- [Bicep Playground](https://aka.ms/bicepdemo)

---

For questions or issues, see [CONTRIBUTING.md](../../CONTRIBUTING.md)
