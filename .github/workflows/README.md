# GitHub Actions Workflows

This directory contains CI/CD workflows for automated building, testing, and deployment.

## Workflows Overview

### Planned Workflows

1. **CI (Continuous Integration)**
   - Triggered on: Pull requests, pushes to main
   - Actions: Lint, test, security scan
   - Purpose: Validate code quality

2. **Infrastructure Validation**
   - Triggered on: Changes to infrastructure/
   - Actions: Bicep validation, linting, security scan
   - Purpose: Validate IaC before deployment

3. **Deploy to Dev**
   - Triggered on: Push to main
   - Actions: Deploy infrastructure and code to dev environment
   - Purpose: Automated dev deployment

4. **Deploy to Production**
   - Triggered on: Manual approval or release tag
   - Actions: Deploy to production with approvals
   - Purpose: Controlled production deployment

5. **Security Scanning**
   - Triggered on: Schedule (daily), pull requests
   - Actions: Dependency scanning, secret detection, SAST
   - Purpose: Continuous security monitoring

## Workflow Best Practices

### Security
- Use GitHub Secrets for sensitive data
- Use OIDC for Azure authentication (no stored credentials)
- Implement least privilege access
- Scan for secrets in commits

### Performance
- Cache dependencies to speed up builds
- Parallelize independent jobs
- Use matrix builds for multi-version testing

### Reliability
- Set appropriate timeouts
- Implement retry logic for flaky steps
- Use environment protection rules

## Example Workflow Structure

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run linting
        run: # linting commands

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: # test commands

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Security scan
        run: # security scanning
```

## GitHub Secrets Required

### Azure Deployment
- `AZURE_CLIENT_ID`: Azure AD application client ID
- `AZURE_TENANT_ID`: Azure AD tenant ID
- `AZURE_SUBSCRIPTION_ID`: Azure subscription ID

### Optional Secrets
- `CODECOV_TOKEN`: For code coverage reporting
- `SLACK_WEBHOOK`: For deployment notifications

## Environment Protection

Configure environments in GitHub repository settings:
- **development**: Auto-deploy, minimal checks
- **staging**: Require approval from 1 reviewer
- **production**: Require approval from 2 reviewers, deployment window

## Status Badges

Add to README.md:
```markdown
![CI](https://github.com/org/ai-metadata-enricher/workflows/CI/badge.svg)
![Security](https://github.com/org/ai-metadata-enricher/workflows/Security/badge.svg)
```

## Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Azure Login Action](https://github.com/Azure/login)
- [Workflow Syntax](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)

---

Workflows will be added as CI/CD requirements are defined.
