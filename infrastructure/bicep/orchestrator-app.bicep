// =====================================================
// Orchestrator Container App — Dev
// =====================================================
// Scope: Deploy the Orchestrator as a Container App in
//        the existing Container Apps Environment.
//
// Features:
//   - System-Assigned Managed Identity
//   - Application Insights via connection string env var
//   - Service Bus connection via namespace env var
//   - No ingress (no external HTTP endpoints)
//   - Minimal resources (0.25 CPU, 0.5Gi memory)
//
// Prerequisites:
//   - Container Apps Environment deployed
//     (see container-apps-env.bicep)
//   - Service Bus namespace with queue created
//   - Container image pushed to a registry
//
// Deploy:
//   az deployment group create \
//     --resource-group rg-ai-metadata-dev \
//     --template-file orchestrator-app.bicep \
//     --parameters \
//       containerAppsEnvironmentName=cae-ai-metadata-dev \
//       containerImage=<acr>.azurecr.io/ai-metadata-orchestrator:dev \
//       serviceBusNamespace=sb-ai-metadata-dev.servicebus.windows.net \
//       appInsightsConnectionString=<connection-string>
//
// Post-deploy:
//   Grant the Container App's Managed Identity the
//   "Azure Service Bus Data Receiver" role on the
//   Service Bus namespace:
//
//   az role assignment create \
//     --assignee <container-app-managed-identity-principal-id> \
//     --role "Azure Service Bus Data Receiver" \
//     --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ServiceBus/namespaces/<ns>

targetScope = 'resourceGroup'

// =====================================================
// Parameters
// =====================================================

@description('Azure region for all resources. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Environment identifier used in resource naming.')
@allowed(['dev', 'test', 'staging', 'prod'])
param environment string = 'dev'

@description('Name of the existing Container Apps Environment.')
param containerAppsEnvironmentName string = 'cae-ai-metadata-${environment}'

@description('Container image reference (e.g. myacr.azurecr.io/ai-metadata-orchestrator:dev).')
param containerImage string

@description('Fully qualified Service Bus namespace (e.g. sb-ai-metadata-dev.servicebus.windows.net).')
param serviceBusNamespace string

@description('Service Bus queue name to consume from.')
param serviceBusQueueName string = 'metadata-ingestion'

@description('Application Insights connection string for telemetry.')
@secure()
param appInsightsConnectionString string = ''

// =====================================================
// Naming Conventions
// =====================================================
// Pattern: ca-{component}-ai-metadata-{env}

var containerAppName = 'ca-orchestrator-ai-metadata-${environment}'

// =====================================================
// Tags
// =====================================================

var tags = {
  environment: environment
  project: 'ai-metadata-enricher'
  component: 'orchestrator'
}

// =====================================================
// Existing Container Apps Environment
// =====================================================

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: containerAppsEnvironmentName
}

// =====================================================
// Orchestrator Container App
// =====================================================

resource orchestratorApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  tags: tags

  // System-Assigned Managed Identity
  identity: {
    type: 'SystemAssigned'
  }

  properties: {
    environmentId: containerAppsEnv.id

    configuration: {
      // No ingress — this is a background worker, not a web app
      ingress: null

      // No secrets — authentication is via Managed Identity
      secrets: []
    }

    template: {
      containers: [
        {
          name: 'orchestrator'
          image: containerImage
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            {
              name: 'SERVICE_BUS_NAMESPACE'
              value: serviceBusNamespace
            }
            {
              name: 'SERVICE_BUS_QUEUE_NAME'
              value: serviceBusQueueName
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
            {
              name: 'ENVIRONMENT'
              value: environment
            }
          ]
        }
      ]

      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

// =====================================================
// Outputs
// =====================================================

@description('Name of the Orchestrator Container App.')
output containerAppName string = orchestratorApp.name

@description('Resource ID of the Orchestrator Container App.')
output containerAppId string = orchestratorApp.id

@description('Principal ID of the System-Assigned Managed Identity.')
output managedIdentityPrincipalId string = orchestratorApp.identity.principalId
