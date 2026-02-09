// =====================================================
// Azure Container Apps Environment — Dev
// =====================================================
// Scope: Provision Container Apps Environment with
//        Log Analytics and Application Insights.
// Does NOT create: containers, apps, secrets, ingress,
//                  VNET, autoscaling, or integrations.
// Deploy:
//   az deployment group create \
//     --resource-group rg-ai-metadata-dev \
//     --template-file container-apps-env.bicep

targetScope = 'resourceGroup'

// =====================================================
// Parameters
// =====================================================

@description('Azure region for all resources. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Environment identifier used in resource naming.')
@allowed(['dev', 'test', 'staging', 'prod'])
param environment string = 'dev'

@description('Log Analytics Workspace retention in days.')
@minValue(30)
@maxValue(730)
param logRetentionDays int = 30

// =====================================================
// Naming Conventions
// =====================================================
// Pattern: {azure-abbreviation}-ai-metadata-{env}
// References:
//   https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/
//     ready/azure-best-practices/resource-abbreviations

var logAnalyticsName = 'log-ai-metadata-${environment}'
var appInsightsName = 'appi-ai-metadata-${environment}'
var containerAppsEnvName = 'cae-ai-metadata-${environment}'

// =====================================================
// Tags
// =====================================================

var tags = {
  environment: environment
  project: 'ai-metadata-enricher'
}

// =====================================================
// Log Analytics Workspace
// =====================================================
// Required dependency for Container Apps Environment
// app logs configuration.

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: logRetentionDays
  }
}

// =====================================================
// Application Insights (workspace-based)
// =====================================================
// Wiring only. Telemetry instrumentation will be
// configured when the Orchestrator Container App
// is created.

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// =====================================================
// Container Apps Environment
// =====================================================
// Consumption-only plan (no workload profiles).
// System-Assigned Managed Identity is NOT available
// at the Environment level — it is configured per
// Container App when created.

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppsEnvName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// =====================================================
// Outputs
// =====================================================
// Exposed for future consumption by the Orchestrator
// Container App deployment.

@description('Name of the Container Apps Environment.')
output containerAppsEnvironmentName string = containerAppsEnv.name

@description('Resource ID of the Container Apps Environment.')
output containerAppsEnvironmentId string = containerAppsEnv.id

@description('Default domain of the Container Apps Environment.')
output defaultDomain string = containerAppsEnv.properties.defaultDomain

@description('Resource ID of the Log Analytics Workspace.')
output logAnalyticsWorkspaceId string = logAnalytics.id

@description('Application Insights connection string for telemetry.')
output appInsightsConnectionString string = appInsights.properties.ConnectionString

@description('Application Insights instrumentation key.')
output appInsightsInstrumentationKey string = appInsights.properties.InstrumentationKey
