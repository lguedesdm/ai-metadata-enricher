# Documentation

This directory contains architecture, governance, and technical documentation for the AI Metadata Enricher platform.

## Directory Structure

```
docs/
├── architecture.md       # System architecture overview
├── governance.md         # Governance and compliance framework
├── incremental-indexing-strategy.md # Conceptual contract for incremental indexing (Blob → Azure AI Search)
├── adr/                 # Architecture Decision Records
│   ├── README.md
│   └── template.md      # ADR template
└── diagrams/            # Architecture diagrams and visuals
    └── README.md
```

## Document Types

### Architecture Documentation
- System architecture and design
- Component interactions and dependencies
- Data flow and processing pipelines
- Integration patterns
- Deployment architecture
- Incremental indexing strategy (conceptual): see [incremental-indexing-strategy.md](incremental-indexing-strategy.md)

### Governance Documentation
- Compliance requirements and controls
- Security policies and standards
- Data governance and privacy
- Audit and monitoring requirements
- Change management processes

### Architecture Decision Records (ADRs)
- Documented architectural decisions
- Context, options considered, and rationale
- Consequences and trade-offs
- Status tracking (proposed, accepted, superseded, deprecated)

### Diagrams
- System architecture diagrams
- Data flow diagrams
- Network topology
- Deployment diagrams
- Sequence diagrams for key flows

## Documentation Standards

All documentation should:
- Be written in Markdown for version control
- Follow clear, professional language
- Include diagrams where helpful (use draw.io, PlantUML, or Mermaid)
- Be kept up-to-date with system changes
- Be reviewed as part of PR process

## Contributing

When making significant architectural changes:
1. Create an ADR documenting the decision
2. Update relevant architecture documentation
3. Update or create diagrams as needed
4. Link ADRs from pull requests

---

For contribution guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md)
