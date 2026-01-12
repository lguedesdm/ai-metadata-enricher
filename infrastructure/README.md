# Infrastructure

This directory contains Infrastructure as Code (IaC) definitions for deploying and managing the AI Metadata Enricher platform on Azure.

## Philosophy

**Infrastructure as Code First** - All Azure resources are defined, versioned, and deployed through code. No manual Azure Portal configuration is permitted for production environments.

## Infrastructure as Code Standard

This project uses **Azure Bicep as the single and authoritative Infrastructure as Code (IaC) standard**.

Terraform is intentionally **not used** in this project to avoid:
- Duplicated infrastructure definitions
- Governance ambiguity
- Operational drift
- Inconsistent RBAC and Managed Identity behavior
- Multiple sources of truth

All Azure resources must be provisioned, updated, and validated exclusively via Bicep.
Manual Azure Portal changes are permitted only for break-glass scenarios.

## Directory Structure

```
infrastructure/
└── bicep/            # Azure Bicep templates and modules
    ├── modules/      # Reusable Bicep modules
    ├── environments/ # Environment-specific configurations
    └── README.md
```

## Core Principles

### 1. Parameterization
- No hardcoded values
- Environment-specific parameters in separate files
- Secrets referenced from Azure Key Vault

### 2. Modularity
- Reusable modules for common patterns
- Composable infrastructure components
- Clear module interfaces and dependencies

### 3. Idempotency
- Safe to run multiple times
- Declarative state management
- Predictable outcomes

### 4. Security
- Principle of least privilege
- Network isolation and security groups
- Managed identities over credentials
- Private endpoints for PaaS services

### 5. Observability
- Diagnostic settings for all resources
- Log Analytics workspace integration
- Application Insights instrumentation
- Azure Monitor alerts and dashboards

## Deployment Workflow

1. **Local Validation**: Lint and validate templates locally
2. **Pull Request**: Submit IaC changes via PR
3. **Automated Validation**: CI pipeline validates syntax and best practices
4. **Plan/Preview**: Generate deployment what-if analysis
5. **Review**: Team reviews infrastructure changes
6. **Deploy**: Automated deployment to target environment
7. **Verify**: Post-deployment validation tests

## Environment Strategy

Typical environments:
- **Development** (`dev`): Individual developer environments or shared dev
- **Test** (`test`): Integration testing environment
- **Staging** (`staging`): Pre-production environment mirroring production
- **Production** (`prod`): Live production environment

Each environment has:
- Separate Azure subscription or resource group
- Environment-specific parameter files
- Appropriate access controls and policies

## Naming Conventions

Follow Azure naming best practices:

```
{resource-type}-{workload}-{environment}-{region}-{instance}
```

Examples:
- `rg-ai-enricher-prod-eastus-01`
- `st-aienricher-prod-eastus-01`
- `func-enricher-prod-eastus-01`

See: [Azure Naming Convention](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming)

## Resource Organization

Resources are organized by:
- **Lifecycle**: Group resources with similar lifecycles
- **Ownership**: Align with team boundaries
- **Security**: Separate security zones
- **Cost Management**: Enable cost tracking and optimization

## State Management

### Bicep
- Deployment state managed by Azure Resource Manager
- Deployment history maintained in Azure subscription
- No external state files required
- Built-in incremental deployment support
- Automatic dependency resolution

## Pre-Deployment Checklist

Before deploying infrastructure:
- [ ] Code reviewed and approved
- [ ] Security scan passed
- [ ] Cost estimate reviewed
- [ ] Deployment plan/what-if reviewed
- [ ] Backup/rollback plan documented
- [ ] Change request approved (for production)

## Azure Resources

Typical resources in this platform:
- Azure Functions (compute)
- Azure Storage (data persistence)
- Azure Event Grid / Service Bus (event processing)
- Azure Cognitive Services (AI services)
- Azure Key Vault (secrets management)
- Azure Monitor / Log Analytics (observability)
- Azure Application Insights (application monitoring)

## Compliance and Governance

- Azure Policy enforcement
- Resource tagging for cost allocation and compliance
- Network security groups and firewalls
- Private endpoints for PaaS services
- Diagnostic and audit logging
- Compliance with organizational standards (FedRAMP, GDPR, etc.)

## Disaster Recovery

- Infrastructure defined in code for rapid redeployment
- Geo-redundant storage for critical data
- Automated backup strategies
- Documented recovery procedures
- Regular DR testing

## Cost Optimization

- Right-sizing resources for workload
- Auto-scaling configurations
- Consumption-based pricing where possible
- Resource cleanup policies
- Cost alerts and budgets

## Documentation

The Bicep implementation includes:
- Module documentation
- Parameter descriptions
- Deployment instructions
- Architecture diagrams
- Troubleshooting guides
- Best practices and patterns

---

For detailed instructions, see:
- [Bicep Documentation](bicep/README.md)
- [Contributing Guidelines](../CONTRIBUTING.md)
- [ADR 0001: Use Bicep as Exclusive IaC](../docs/adr/0001-use-bicep-as-exclusive-iac.md)
