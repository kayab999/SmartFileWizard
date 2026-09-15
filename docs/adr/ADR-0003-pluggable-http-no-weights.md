# ADR-0003: Providers HTTP pluggables sin pesos en el wheel

- Status: **Accepted**
- Date: 2026-08-11
- Author: architect (Grok)

## Context

Hardware y GGUF cambian; FileWizard no puede empaquetar modelos.

## Decision

- Contrato OpenAI-compatible HTTP (`llama_http`) + tesseract local opcional.
- Config en `perception.yaml` (`model`, `base_url`).
- Zero-shot vía extra `[zeroshot]` (torch/transformers), lazy load.
- Cache y journal guardan features/snapshots, no pesos.

## Consequences

- Docs y scripts (`start-perception.sh`) orientan al usuario a levantar servers.
- Nuevos backends = nuevo `provider` string + extractor, sin romper `features` shape.

## Alternatives rejected

- Vendoring GGUF en el repo.
- SDK cloud obligatorio.
