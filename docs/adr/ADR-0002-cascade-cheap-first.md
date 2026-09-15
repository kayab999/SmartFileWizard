# ADR-0002: Cascada barato-primero

- Status: **Accepted**
- Date: 2026-08-11
- Author: architect (Grok)

## Context

Llamar OCR + VLM en cada imagen es lento e innecesario. El perfil `recommended` debe ser usable en carpetas grandes.

## Decision

`CascadeExtractor` orquesta:

```text
0 heuristics → 1 zeroshot (opcional) → 2 OCR → 3 VLM
```

con early-stop en `status=confirmed` y umbrales en `CascadeSettings`.  
El perfil `recommended` activa `cascade.enabled=true` (no dual full-scan paralelo).

## Consequences

- Factory devuelve un extractor `cascade` (posible wrap `CachingExtractor`).
- Tests de regresión: `test_recommended_uses_cascade`.

## Alternatives rejected

- Siempre OCR+vision en paralelo (0.4.0 legacy path solo si cascade off).
