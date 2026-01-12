# ADR 0001 — Use Azure Bicep as Exclusive IaC

## Status

Accepted

## Date

2026-01-12

## Decision Makers

- Architecture Team
- Platform Engineering Team
- Security & Governance Team

## Context

This project is an Azure-native, public-sector, governed platform with strict requirements for:
- **Auditability**: All infrastructure changes must be traceable and compliant
- **Security**: Managed identities, private endpoints, and Azure Policy enforcement
- **Governance**: FedRAMP, GDPR, and other compliance frameworks
- **Operational Excellence**: Single source of truth for infrastructure state
- **Developer Experience**: Clear, consistent tooling without ambiguity

Infrastructure as Code (IaC) is fundamental to this platform. We needed to select a single, authoritative IaC standard to avoid:
- Duplicated infrastructure definitions
- Governance ambiguity (which tool is authoritative?)
- Operational drift between IaC tools
- Inconsistent resource configurations
- Developer confusion about which tool to use
- Maintenance burden of multiple IaC languages

## Considered Options

### Option 1: Azure Bicep Only

**Description**: Use Azure Bicep as the exclusive IaC language for all infrastructure provisioning.

**Pros**:
- Native Azure tooling with first-class ARM integration
- Automatic state management via Azure Resource Manager (no external state files)
- Best-in-class support for new Azure features (day-0 support)
- Type safety and IntelliSense in VS Code
- No external state management required (no risk of state file corruption)
- Simpler RBAC model (Azure AD integrated)
- Clearer governance story for Azure-only projects
- Lower cognitive load for team (single IaC language)
- Better alignment with Azure Policy and compliance frameworks
- Native support for managed identities and Azure-native security patterns

**Cons**:
- Azure-only (not multi-cloud compatible)
- Smaller community compared to Terraform (though growing rapidly)
- Team may need training if coming from Terraform background

### Option 2: Terraform Only

**Description**: Use HashiCorp Terraform as the exclusive IaC language.

**Pros**:
- Multi-cloud capability (Azure, AWS, GCP)
- Large community and ecosystem
- Mature tooling and patterns
- Extensive module registry

**Cons**:
- Requires external state management (Azure Storage + locking)
- State files can contain secrets (security risk)
- Lag time for new Azure features (days to weeks)
- Additional complexity in CI/CD (state backend configuration)
- Not as tightly integrated with Azure governance (Policy, Blueprints)
- Overhead of managing state files across environments
- Potential for state corruption or conflicts

### Option 3: Support Both Bicep and Terraform

**Description**: Allow teams to choose between Bicep or Terraform based on preference.

**Pros**:
- Flexibility for different scenarios
- Teams can use familiar tools

**Cons**:
- **Two sources of truth** (which one is authoritative?)
- Duplicated effort maintaining both
- Risk of configuration drift
- Governance nightmare (which tool was used to deploy what?)
- Inconsistent patterns and practices
- Higher maintenance burden
- Confusion for new team members
- Difficult to enforce standards

## Decision

**Azure Bicep is the exclusive Infrastructure as Code (IaC) standard for this project.**

Terraform is explicitly **not used** and will not be accepted in code contributions.

### Rationale

1. **Azure-Native Platform**: This is a 100% Azure platform with no multi-cloud requirements. Bicep's tight Azure integration provides the best developer experience and feature coverage.

2. **Governance & Compliance**: Bicep's native ARM integration aligns perfectly with Azure Policy, Blueprints, and compliance frameworks required for public-sector deployments.

3. **Security**: No external state files means no risk of state file leakage or corruption. All state is managed securely within Azure Resource Manager.

4. **Operational Simplicity**: Single IaC language eliminates ambiguity about which tool is authoritative and reduces operational complexity.

5. **Developer Experience**: Type safety, IntelliSense, and Azure-first tooling provide superior DX for Azure development.

6. **Day-0 Feature Support**: Bicep typically supports new Azure features immediately, critical for a rapidly evolving AI/ML platform.

7. **Lower Risk**: No state file management eliminates entire classes of operational risks (state corruption, state locking issues, secret leakage in state).

## Consequences

### Positive Consequences

- **Single Source of Truth**: All infrastructure is defined in one language
- **Simplified Governance**: Clear ownership and auditability
- **Reduced Complexity**: No state file management, no multi-tool confusion
- **Better Azure Integration**: Native support for all Azure features
- **Improved Security**: No state files to secure or leak
- **Faster Onboarding**: New team members learn one IaC language
- **Consistent Patterns**: All modules and templates follow same conventions
- **Lower Maintenance**: Only one set of modules to maintain

### Negative Consequences

- **Azure Lock-In**: Cannot easily migrate to other cloud providers (accepted trade-off)
- **Team Training**: Teams familiar with Terraform will need Bicep training
- **Smaller Ecosystem**: Bicep module ecosystem is smaller than Terraform (though growing)

### Neutral Consequences

- **Tooling Investment**: Need to standardize on Bicep linting, validation, and CI/CD patterns
- **Documentation**: All IaC documentation must be Bicep-focused

## Implementation

### Immediate Actions

- [x] Remove `infrastructure/terraform/` directory from repository
- [x] Update `infrastructure/README.md` to reflect Bicep-only policy
- [x] Update root `README.md` with Bicep-only references
- [x] Update `CONTRIBUTING.md` to reject Terraform contributions
- [x] Create this ADR documenting the decision

### Follow-up Actions

- [ ] Create Bicep module library for common patterns
- [ ] Develop Bicep linting rules in CI/CD pipeline
- [ ] Create training materials for team on Bicep best practices
- [ ] Establish Bicep code review checklist
- [ ] Document Bicep patterns in `infrastructure/bicep/` directory

## Related Decisions

- None yet (this is the first ADR)

## References

- [Azure Bicep Documentation](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/)
- [Azure Well-Architected Framework](https://learn.microsoft.com/en-us/azure/architecture/framework/)
- [Bicep vs ARM Templates vs Terraform](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/compare-template-specs)
- [Project Architecture Documentation](../architecture.md)
- [Project Governance Documentation](../governance.md)

## Notes

This decision was made during initial project setup to establish clear standards before infrastructure development begins. It may be revisited if the project scope changes to include multi-cloud requirements, but such a change would require significant architectural review and approval from the governance board.

---

**Review Date**: 2027-01-12 (annual review)  
**Last Updated**: 2026-01-12  
**Version**: 1.0
