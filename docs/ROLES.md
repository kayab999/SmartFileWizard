# División de trabajo — FileWizard

**Producto:** FileWizard `0.11.0`  
**Fecha:** 2026-08-11  
**Objetivo:** dos agentes con responsabilidades disjuntas y handoff limpio.

---

## 1. Mapa de roles

| Rol | Quién | Herramienta típica | Hace | No hace |
|-----|--------|-------------------|------|---------|
| **Arquitecto / auditor** | Grok (xAI) | esta sesión / revisión | Diseño, contratos, planes, DoD, review de diffs, invariantes | Implementar features grandes de forma rutinaria |
| **Implementador** | DeepSeek V4 | OpenCode | Código, tests, commits locales, green suite | Cambiar arquitectura sin ADR; saltarse DoD |
| **Product owner** | Carlos (humano) | — | Prioridad, “sí/no”, release, smoke real con GGUF | — |

```text
                    Carlos (prioridad)
                          │
          ┌───────────────┴───────────────┐
          ▼                               ▼
   Arquitecto (Grok)               Implementador (DeepSeek)
   · contratos                     · WPs del WORK_PLAN
   · WORK_PLAN / ADRs              · tests + código
   · audit de PR/diff              · no reinventar capas
          │                               │
          └────────── review ◄────────────┘
                          │
                     merge / release
```

---

## 2. Principio de producto (no negociable)

> **Perception provides evidence · Rules decide · The journal undoes.**

Cualquier cambio que:

- mueva archivos fuera de `executor`,
- haga OCR/VLM obligatorio para importar el core,
- rompa dry-run por defecto, o
- deje de auditar con `ConditionCheck` / journal,

**se rechaza en auditoría** aunque “funcione”.

Carta de robustez: [ROBUSTNESS.md](./ROBUSTNESS.md) (R1–R15).

---

## 3. Responsabilidades del arquitecto (Grok)

1. Mantener **contratos** (`Condition`, `FileFacts.features`, `FeatureExtractor`, journal schema, pipeline hooks).
2. Escribir/actualizar **WORK_PLAN** (paquetes de trabajo con I/O y DoD).
3. Emitir **ADR** cortos cuando hay decisión de diseño (ver `docs/adr/`).
4. **Auditar** el trabajo del implementador: diff, tests, riesgos, deuda.
5. Actualizar **AGENTS.md** status y **ROADMAP** al cerrar hitos.
6. Decidir orden de hitos (0.5 → 0.6 → 0.7) y qué queda fuera de scope.

**No** debe ser el único que escribe código de features: prioriza revisión y diseño.

---

## 4. Responsabilidades del implementador (DeepSeek / OpenCode)

1. Leer **en este orden** antes de tocar código:
   1. [IMPLEMENTER_BRIEF.md](./IMPLEMENTER_BRIEF.md) *(entrada rápida)*
   2. WP activo en [WORK_PLAN.md](./WORK_PLAN.md)
   3. [AGENTS.md](../AGENTS.md) §3.4 (invariantes) si toca core
   4. Módulos listados en el WP
2. Implementar **un WP a la vez** (o subtarea marcada).
3. Añadir/ajustar **tests** del WP; `pytest -q` verde antes de declarar done.
4. No ampliar scope (“ya que estoy…”). Abrir nota en `docs/BACKLOG_NOTES.md` si aparece trabajo extra.
5. Si el WP es ambiguo o choca con un invariante: **parar** y documentar pregunta en el PR / nota; no inventar arquitectura.

### Estilo de código (obligatorio)

- Identificadores y comentarios de API: **inglés**.
- Strings de UI visibles: **español** (como el resto de la GUI).
- Funciones cortas, early returns, sin nesting profundo.
- Sin dependencias nuevas en el core sin estar en el WP o en un ADR.
- Extras opcionales (`[zeroshot]`, `[ocr]`, `[ui]`) no pueden ser imports top-level del core.

---

## 5. Protocolo de handoff

### Implementador → Arquitecto (fin de WP)

Entregar en el mensaje / PR:

```text
WP-ID: WPx.y
Resumen: 2–4 frases
Archivos tocados: …
Tests: pytest -q → N passed
Cómo probar manualmente: …
Decisiones tomadas (si hubo): …
Bloqueos / preguntas: …
```

### Arquitecto → Implementador (review)

```text
Verdict: APPROVE | REQUEST_CHANGES | REDESIGN
Findings: (bloqueantes primero)
Invariantes: OK / rotos
Siguiente WP: …
```

### Humano

- Prioriza qué WP activar.
- Smoke con hardware real (llama-server, GPU).
- Decide release / bump de versión (el WP lo propone; el humano confirma).

---

## 6. Documentos del sistema de trabajo

| Documento | Dueño principal | Uso |
|-----------|-----------------|-----|
| [IMPLEMENTER_BRIEF.md](./IMPLEMENTER_BRIEF.md) | Arquitecto | Primer archivo que abre OpenCode |
| [WORK_PLAN.md](./WORK_PLAN.md) | Arquitecto | Cola de WPs implementables |
| [AGENTS.md](../AGENTS.md) | Arquitecto | Arquitectura + status + mapa de módulos |
| [ROADMAP.md](./ROADMAP.md) | Arquitecto | Hitos de producto |
| [ROBUSTNESS.md](./ROBUSTNESS.md) | Ambos (lectura) | R1–R15 |
| [DEFINITION_OF_DONE.md](./DEFINITION_OF_DONE.md) | Arquitecto | Checklist por WP / release |
| [docs/adr/](./adr/) | Arquitecto | Decisiones que no caben en un WP |
| [BACKLOG_NOTES.md](./BACKLOG_NOTES.md) | Implementador | Ideas fuera de scope |
| [USER_MANUAL.md](./USER_MANUAL.md) | Ambos al cerrar UX | Manual usuario |
| PLAN_CASCADE / PLAN_PERCEPTION | Arquitecto | Diseño histórico + estado |

---

## 7. Qué está cerrado (no reabrir sin ADR)

- Pipeline compartido CLI/UI (`pipeline.plan_operations`).
- Cascada barato-primero (`CascadeExtractor`), no dual full-scan en `recommended`.
- Journal + undo seguro; columna `perception` compacta.
- Review queue JSON + UI básica.
- Cache por hash de contenido + fingerprint de config.
- Condiciones `cascade_category_any` / `cascade_status_any` / `cascade_min_confidence`.

---

## 8. Stack de tools sugerido

| Tarea | Tool |
|-------|------|
| Codificación general, tests, refactors locales | OpenCode + DeepSeek V4 |
| Diseño de hito, MCP contract, auditoría de PR | Grok (arquitecto) |
| Smoke UI / GGUF real | Humano (Carlos) |
