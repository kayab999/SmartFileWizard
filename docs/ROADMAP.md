# FileWizard — Roadmap

**Principio:** la percepción aporta evidencia · las reglas deciden · el journal deshace.

Consumidores del core (mismo `pipeline` / `RuleSet` / journal):

```text
CLI  ·  GUI  ·  MCP (desde 0.7.0)  ·  (daemon)
```

**Implementación ejecutable (DeepSeek/OpenCode):** no uses solo esta tabla — sigue los work packages en **[WORK_PLAN.md](./WORK_PLAN.md)**.  
**Roles:** [ROLES.md](./ROLES.md) · **Brief:** [IMPLEMENTER_BRIEF.md](./IMPLEMENTER_BRIEF.md).

---

## Hecho

| Versión | Entrega |
|---------|---------|
| 0.1.x | Core + CLI + dry-run + journal + undo + hardening |
| 0.2.x | GUI wizard PySide6 |
| 0.3.0 | Heurísticas, negaciones, thumbnail, journal UI, robustez |
| 0.3.1 | `pipeline` compartido · UI cascada = CLI RuleSet |
| 0.3.2 | Preview agrupado por destino |
| 0.3.3 | **Presets** (biblioteca RuleSet + CLI + UI) |
| **0.4.0** | Progreso/cancel + **perception providers** (GLM-OCR + Qwen3-VL-2B defaults, HTTP pluggable) |
| **0.4.1** | UI Ajustes de percepción (URLs/modelos) |
| **0.4.2** | **Cascada** barato→OCR→VLM (`CascadeExtractor` + umbrales en Ajustes); doc `PLAN_CASCADE.md` |
| **0.4.3** | Etapa 1 zero-shot (CLIP/SigLIP, extra `filewizard[zeroshot]`); condiciones `cascade_*`; cola revisión manual (JSON + UI) |
| **0.4.4** | Cache percepción por hash de archivo; snapshot compacto en journal (`operations.perception`) |
| **0.5.0** | Catálogo modelos + `filewizard perception models` · condición `cascade_stage_max` · **agent feature inject** (`--agent-features`, base para MCP 0.7) · preset cascade-aware `images-cascade-ml` |
| **0.6.0** | **Watcher**: `watch once` (tick) → `watch --interval` (polling + debounce por mtime/size + pid lock) → **active watches** (`active_watches.yaml` + `watch list|add|remove|run`) |
| **0.7.0** | **MCP server** (stdio): 9 tools — read (presets, journal, facts) · mutación gate `confirm=true` exacto (plan/execute/undo) · `apply_agent_labels` (labels → plan dry-run, sin mutar FS) | WP-0.7.1 … 0.7.5 |
| **0.8.0** | UX + calidad: MCP plan/execute usan percepción; fix categoría factura; home badge/cola/intent ML; evidencia en journal/preview; Ajustes scroll+catálogo; watch tick en GUI | [AUDIT_0.8.md](./AUDIT_0.8.md) |
| **0.9.0** | Runtime: progreso execute, watch QThread + sleep cancelable, cola `.bak`, HTTP 1-inflight, log GUI, WAL, cache 64MiB, MCP `allowed_roots`, CLI pending warn | [AUDIT_0.9.md](./AUDIT_0.9.md) |
| **0.10.0** | Remediación + afilado de reglas/templates | SHIPPED |
| **0.10.1** | Auditoría Fase 1: spoof screenshot, MCP limit, presets atómicos | SHIPPED |
| **0.11.0** | Preset downloads-docs; labels de revisión en el siguiente plan; older/aspect; `.desktop` | SHIPPED |

---

## Próximo

| Versión | Núcleo | Entrega | Work packages |
|---------|--------|----------|---------------|
| **0.12+** | N2/N5 | Extra backends (4B, NPU), daemon/inotify, Flatpak | tras OK humano; no inventar WPs |

0.8–0.9 shipped: [CHANGELOG.md](../CHANGELOG.md) · [RELEASE.md](./RELEASE.md).  
WPs históricos: **[WORK_PLAN.md](./WORK_PLAN.md)**.

Diseño detallado: **[PLAN_PERCEPTION_PROVIDERS.md](./PLAN_PERCEPTION_PROVIDERS.md)**.

### Defaults de percepción (producto)

```text
Lite:          heurísticas + Tesseract opcional
Recommended:   cascada ON → stage0 heuristics → stage1 CLIP opcional
               → stage2 GLM-OCR (:8080) → stage3 Qwen3-VL-2B (:8081)
Power:         mismo conector, modelo visión 4B u otro GGUF
Agent:         sin GGUF local; evidencia vía MCP (desde 0.7.0)
```

Extras: `filewizard[zeroshot]` (etapa 1) · cache en `perception_cache/` · snapshot en journal.

Los pesos **no** van en el paquete Python; el usuario elige hardware cambiando `model` / `base_url` en config.

Diseño cascada: **[PLAN_CASCADE.md](./PLAN_CASCADE.md)**.

---

## MCP (0.7) — por qué y cómo

### Motivación (tendencias)

- Los agentes (Claude, Cursor, Grok, etc.) se integran con herramientas vía **MCP**, no solo con CLI ad-hoc.
- FileWizard ya es un **motor local de reglas + journal**; exponerlo por MCP lo convierte en *tool* de primera clase para agentes.
- Si el **modelo del agente tiene visión**, puede clasificar/etiquetar imágenes en el lado del agente y **inyectar evidencia** (o decidir destinos vía reglas generadas), sin obligar a empaquetar un modelo de visión local en FileWizard.
- En la práctica: **ahorra un VLM local** en la máquina del usuario para muchos flujos; el core sigue siendo determinista y auditable.
- **Ya disponible desde 0.5.3:** `perception/inject.py` + `filewizard run --agent-features path.json` (JSON `path → {vision, ocr, cascade}`); el agente corre **después** de la cascada y sobreescribe (override). En **0.7.0**: MCP expone esto vía tool `filewizard_apply_agent_labels` (labels → plan dry-run, sin mutar FS).

### Arquitectura (0.7.0 shipped)

```text
                    Agent (con o sin visión)
                              │
                              │ MCP tools (stdio)
                              ▼
                    filewizard mcp serve / filewizard-mcp
                              │
                              ▼
                    pipeline · engine · executor · journal
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         heuristics        OCR?           vision?
         (local)         (local)     (local optional
                                      OR agent-supplied
                                      labels in features)
```

### Tools MCP (0.7.0, shipped)

| Tool | Rol | Mutación |
|------|-----|----------|
| `ping` | Liveness | No |
| `filewizard_version` | Versión del producto | No |
| `filewizard_list_presets` | Biblioteca de RuleSet | No |
| `filewizard_journal_batches` | Historial por lotes | No |
| `filewizard_collect_facts` | Metadatos/heurísticas de un path (sin mover) | No |
| `filewizard_plan` | Dry-run: source + preset/rules → plan + explanations | No |
| `filewizard_execute` | Aplicar plan / execute | Sí — exige `confirm=true` exacto |
| `filewizard_undo_batch` | Undo por `batch_id` (dry-run default) | Sí — exige `confirm=true` exacto |
| `filewizard_apply_agent_labels` | Inyectar `features` del agente en un plan dry-run | No |

Config ejemplo para agentes (Claude Code / Cursor):

```json
{ "mcpServers": { "filewizard": { "command": "filewizard", "args": ["mcp", "serve"] } } }
```

### Invariantes MCP (no negociables)

1. Dry-run por defecto en tools de mutación; execute explícito.
2. Mismo journal y misma carta de robustez (R1–R15).
3. La IA del agente **no mueve archivos** fuera del executor.
4. Visión del agente = **evidencia opcional**, no sustituye reglas salvo que el usuario pida “generar preset desde conversación”.
5. Sin telemetría ni cloud obligatoria.

### Relación con visión local

| Escenario | Enfoque |
|-----------|---------|
| Usuario solo CLI/GUI, sin agente | Heurísticas + OCR; visión local solo si instala plugin |
| Usuario + agente con visión | Agente etiqueta → reglas / features; **sin modelo local** |
| Offline total + clasificación semántica | Plugin visión local (0.5), opcional |

---

## No prioritario

- Reescritura Tauri/Rust del core  
- File manager dual-pane  
- Cloud sync  
- Modelo de visión embebido en el binario principal  
