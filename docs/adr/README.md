# Architecture Decision Records (ADR)

Decisiones de diseño **estables** que el implementador no debe reinterpretar.

| ID | Título | Status |
|----|--------|--------|
| ADR-0001 | Separación percepción / reglas / journal | Accepted |
| ADR-0002 | Cascada barato-primero (no dual full-scan) | Accepted |
| ADR-0003 | Providers HTTP pluggables sin pesos en el wheel | Accepted |
| ADR-0004 | MCP como consumidor del pipeline, no fork del core | Accepted (2026-08-11) |

Formato de un ADR nuevo: `docs/adr/ADR-NNNN-titulo-corto.md`

```markdown
# ADR-NNNN: Título

- Status: Proposed | Accepted | Superseded
- Date: YYYY-MM-DD
- Author: architect

## Context
## Decision
## Consequences
## Alternatives rejected
```

El implementador **no** crea ADRs salvo que el WP lo pida; si choca con un ADR accepted, para y pregunta.
