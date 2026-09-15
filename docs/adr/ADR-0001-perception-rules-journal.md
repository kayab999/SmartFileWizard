# ADR-0001: Separación percepción / reglas / journal

- Status: **Accepted**
- Date: 2026-08-11
- Author: architect (Grok)

## Context

FileWizard puede usar OCR, VLM y zero-shot. Sin límites, la “IA” tendería a mover archivos o a acoplar destinos al modelo.

## Decision

Tres capas estrictas:

1. **Perception** → solo `features` (dict auditable).
2. **Rules / engine** → deciden match + acción (`Condition` / `Action`).
3. **Executor + journal** → mutan FS y permiten undo.

Los consumidores (CLI, UI, futuro MCP) no reimplementan FS.

## Consequences

- Nuevos modelos = nuevos extractors / stages, no nuevas rutas de move.
- UI y MCP son thin clients del `pipeline`.

## Alternatives rejected

- “El VLM elige la carpeta” sin reglas.
- File manager AI con side-effects implícitos.
