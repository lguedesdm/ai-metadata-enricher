# Contributing to AI Metadata Enricher

Thank you for your interest in contributing to the AI Metadata Enricher platform. This document provides guidelines and standards for contributing to this enterprise project.

## Code of Conduct

This project adheres to professional standards of conduct. All contributors are expected to:
- Treat others with respect and professionalism
- Focus on constructive feedback and collaboration
- Maintain confidentiality of sensitive information
- Follow organizational policies and procedures

## Getting Started

### Prerequisites

1. Familiarity with Git and GitHub workflows
2. Understanding of Azure cloud services
3. Knowledge of Infrastructure as Code (Azure Bicep)
4. Experience with relevant programming languages used in this project

### Development Environment Setup

1. Clone the repository
2. Review the [Architecture Documentation](docs/architecture.md)
3. Set up local development tools as specified in project documentation
4. Configure Azure CLI and authenticate to the appropriate subscription

## Contribution Workflow

### 1. Branch Strategy

- `main` - Production-ready code, protected branch
- `develop` - Integration branch for features
- `feature/*` - Feature development branches
- `bugfix/*` - Bug fix branches
- `hotfix/*` - Emergency production fixes

### 2. Making Changes

1. **Create a Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Your Changes**
   - Follow coding standards and conventions
   - Write clear, descriptive commit messages
   - Include tests for new functionality
   - Update documentation as needed

3. **Commit Guidelines**
   - Use conventional commit format:
     ```
     <type>(<scope>): <subject>
     
     <body>
     
     <footer>
     ```
   - Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`, `perf`
   - Example: `feat(contracts): add metadata enrichment schema`

4. **Push and Create Pull Request**
   ```bash
   git push origin feature/your-feature-name
   ```

### 3. Pull Request Requirements

All pull requests must:
- [ ] Have a clear, descriptive title
- [ ] Include a detailed description of changes
- [ ] Reference related issues or tickets
- [ ] Pass all automated checks (linting, tests, security scans)
- [ ] Include updated documentation
- [ ] Be reviewed and approved by at least one code owner
- [ ] Have no merge conflicts with target branch

## Development Standards

### Infrastructure as Code

- **All infrastructure must be defined using Azure Bicep exclusively**
- Terraform-based contributions will not be accepted
- No manual Azure Portal changes (except break-glass scenarios)
- Include parameter files for different environments (`.bicepparam`)
- Document all resources and their purpose
- Follow Bicep best practices and linting rules

### Security

- **Never commit secrets, keys, or credentials**
- Use Azure Key Vault references for sensitive values
- Follow principle of least privilege
- Implement defense in depth
- Run security scanning tools before committing

### Documentation

- Update README.md for user-facing changes
- Create Architecture Decision Records (ADR) for significant decisions
- Document API changes in contracts/docs/
- Keep diagrams current with architecture changes

### Testing

- Write unit tests for all business logic
- Include integration tests for critical paths
- Ensure tests are repeatable and independent
- Maintain test coverage above project threshold

## Code Review Process

1. **Automated Validation**: CI/CD pipeline runs automatically
2. **Peer Review**: At least one team member reviews code
3. **Security Review**: Security team reviews for sensitive changes
4. **Approval**: Designated code owners approve merge

## Versioning and Releases

- Follow Semantic Versioning (SemVer): MAJOR.MINOR.PATCH
- Update CHANGELOG.md with all notable changes
- Tag releases in Git
- Create release notes for production deployments

## Architecture Decision Records (ADRs)

For significant architectural decisions:
1. Create a new ADR in `docs/adr/`
2. Use the ADR template
3. Include context, decision, and consequences
4. Get team consensus before implementation

## Questions and Support

- **Technical Questions**: Open a GitHub Discussion
- **Bug Reports**: Create a GitHub Issue with template
- **Security Issues**: Follow security reporting procedures (do not create public issues)

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.

---

**Thank you for contributing to the AI Metadata Enricher platform!**
