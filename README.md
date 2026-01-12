# AI Metadata Enricher

> Enterprise Azure AI platform for metadata enrichment and intelligent content processing

## Overview

The AI Metadata Enricher is a production-grade, event-driven platform designed for public-sector and enterprise environments requiring governed, auditable, and secure metadata processing capabilities using Azure AI services.

## Architecture Principles

- **Dev-First**: Developer experience and productivity prioritized
- **IaC-First**: All infrastructure defined as code using Azure Bicep exclusively
- **Event-Driven**: Asynchronous, scalable processing architecture
- **Governed**: Compliance-ready with audit trails and policy enforcement
- **Cloud-Native**: Built for Azure, following Well-Architected Framework

## Repository Structure

```
ai-metadata-enricher/
├── contracts/          # API contracts, schemas, and design-time definitions
├── infrastructure/     # Infrastructure as Code (Bicep)
├── docs/              # Architecture, governance, and technical documentation
├── src/               # Application source code
├── tests/             # Automated tests
└── .github/           # GitHub workflows and templates
```

## Documentation

- [Architecture Overview](docs/architecture.md)
- [Governance and Compliance](docs/governance.md)
- [Architecture Decision Records](docs/adr/)
- [Contributing Guidelines](CONTRIBUTING.md)

## Getting Started

### Prerequisites

- Azure subscription with appropriate permissions
- Azure CLI (`az`) installed and configured
- Bicep CLI (installed via Azure CLI)
- Git for version control

### Infrastructure Deployment

Infrastructure provisioning documentation is available in the [infrastructure/](infrastructure/) directory. All resources are provisioned via Infrastructure as Code - no manual Azure Portal configuration.

## Security and Compliance

- **No Secrets in Repository**: All sensitive values managed via Azure Key Vault or environment configuration
- **Audit Trails**: All operations logged and auditable
- **Policy Enforcement**: Azure Policy and governance controls applied
- **Public Sector Ready**: Designed for FedRAMP, GDPR, and similar compliance frameworks

## Support and Contributing

Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on contributing to this project.

## License

[Specify License - typically MIT, Apache 2.0, or organization-specific]

## Governance

This repository follows enterprise governance standards. All changes require:
- Pull request review
- Automated validation (linting, security scanning, tests)
- Approval from designated code owners

---

**Status**: Active Development  
**Maintained By**: [Organization Name]  
**Last Updated**: January 2026
