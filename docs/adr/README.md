# Architecture Decision Records (ADRs)

## What is an ADR?

An Architecture Decision Record (ADR) is a document that captures an important architectural decision made along with its context and consequences.

## Why ADRs?

- **Documentation**: Preserve the reasoning behind decisions
- **Communication**: Share decisions with team and stakeholders
- **Onboarding**: Help new team members understand the system
- **Review**: Facilitate review of past decisions
- **Accountability**: Track who made decisions and why

## When to Write an ADR

Create an ADR for decisions that:
- Are structurally significant
- Affect multiple components or teams
- Are difficult or expensive to reverse
- Involve trade-offs between competing concerns
- Establish patterns for future development
- Address security, compliance, or governance requirements

## ADR Lifecycle

### Status Values

- **Proposed**: Under discussion, not yet decided
- **Accepted**: Approved and should be implemented
- **Superseded**: Replaced by another ADR (reference the new ADR)
- **Deprecated**: No longer recommended but still in use
- **Rejected**: Decision was made not to proceed

## ADR Template

Use the template in [template.md](template.md) for all new ADRs.

## Naming Convention

```
NNNN-short-title.md
```

- `NNNN`: Four-digit sequential number (e.g., 0001, 0002)
- `short-title`: Brief, kebab-case description
- Examples:
  - `0001-use-azure-functions.md`
  - `0002-event-grid-vs-service-bus.md`
  - `0003-cosmos-db-partitioning-strategy.md`

## Directory Structure

```
adr/
├── README.md           # This file
├── template.md         # ADR template
├── 0001-example.md     # Example ADR
└── ...                 # Additional ADRs
```

## Creating a New ADR

1. Copy `template.md` to a new file with appropriate number and title
2. Fill in all sections:
   - Title
   - Status
   - Context
   - Decision
   - Consequences
   - Metadata (date, decision makers)
3. Submit as part of pull request
4. Link ADR from PR description
5. Get team review and approval

## ADR Review Process

1. **Author** writes ADR and submits PR
2. **Team** reviews context and options
3. **Discussion** on alternatives and trade-offs
4. **Decision** made by designated decision makers
5. **Status** updated to "Accepted" or "Rejected"
6. **Implementation** proceeds if accepted

## Tips for Writing Good ADRs

### Context Section
- Explain the problem or opportunity
- Describe the forces at play (constraints, requirements)
- Include relevant background information
- Reference related ADRs

### Decision Section
- State the decision clearly and concisely
- Explain why this option was chosen
- Describe the approach in sufficient detail
- Include diagrams if helpful

### Consequences Section
- List positive consequences (benefits)
- List negative consequences (costs, risks)
- Describe impact on system and team
- Note any follow-up actions needed

### General Tips
- Write in active voice
- Be specific and concrete
- Avoid jargon when possible
- Include references and links
- Keep it concise but complete

## Superseding an ADR

When an ADR is superseded:
1. Create new ADR documenting the new decision
2. Update old ADR status to "Superseded by ADR-XXXX"
3. Explain why the decision changed
4. Link between the old and new ADRs

## ADR Index

### Infrastructure Decisions
- [ADR-0001](0001-use-bicep-as-exclusive-iac.md) - Use Azure Bicep as Exclusive IaC (Accepted)

### Data Architecture Decisions
- (Future ADRs will be listed here)

### Security Decisions
- (Future ADRs will be listed here)

### Integration Decisions
- (Future ADRs will be listed here)

## Tools

Recommended tools for ADR management:
- [adr-tools](https://github.com/npryce/adr-tools) - Command-line tools for ADRs
- [log4brains](https://github.com/thomvaill/log4brains) - Architecture knowledge base

## References

- [ADR GitHub Organization](https://adr.github.io/)
- [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
- [Architecture Decision Records](https://github.com/joelparkerhenderson/architecture-decision-record)

---

**Maintained By**: Architecture Team  
**Last Updated**: January 2026
