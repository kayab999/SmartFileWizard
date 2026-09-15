# Work Plan — Implementación (DeepSeek / OpenCode)

**Baseline de producto:** `0.11.0` (224 tests, suite verde)  
**Dueño del plan:** arquitecto (Grok)  
**Ejecutor:** implementador (DeepSeek V4 vía OpenCode)  
**Roles:** [ROLES.md](./ROLES.md) · **Brief:** [IMPLEMENTER_BRIEF.md](./IMPLEMENTER_BRIEF.md) · **DoD:** [DEFINITION_OF_DONE.md](./DEFINITION_OF_DONE.md)

### Leyenda de status

| Status | Significado |
|--------|-------------|
| `READY` | Puede empezarse ya |
| `IN_PROGRESS` | Alguien lo está haciendo |
| `IN_REVIEW` | Código listo; espera audit Grok |
| `DONE` | Audit APPROVE + mergeado en la línea de trabajo |
| `BLOCKED` | Falta decisión humana/arquitecto |
| `DEFERRED` | Consciente, no ahora |

### Orden obligatorio

```text
WP-0.5.*  →  WP-0.6.*  →  WP-0.7.*  →  WP-0.8.*
```

Hitos 0.5–0.9 **SHIPPED**. Siguiente: **0.10+** (tras OK humano; no inventar WPs).  
Dentro de un hito: orden numérico. Auditoría: [AUDIT_0.9.md](./AUDIT_0.9.md).

---

# Hito 0.5 — Backends y contratos de percepción (sin romper features)

**Meta de producto:** poder apuntar a otros modelos/endpoints y endurecer el contrato de features **sin** cambiar la forma de `ocr` / `vision` / `cascade` que consumen las reglas.

**Version bump:** al cerrar el hito completo → `0.5.0` (último WP del hito).

---

## WP-0.5.1 — Catálogo de modelos conocidos + validación suave de config

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P0 |
| **Estimación** | S (pequeño) |

### Objetivo

Documentar y exponer en código un catálogo **informativo** de modelos conocidos (no descarga automática) y usarlo en Ajustes / CLI status para ayudar a elegir `model` / `base_url` sin hardcodear magia.

### I/O contract

**In**

- `PerceptionConfig` actual (ocr/vision/cascade/cache).

**Out**

- Módulo `src/filewizard/perception/catalog.py` (o similar) con lista de entradas:
  - `role`: `ocr` | `vision` | `zeroshot`
  - `id`: string estable
  - `default_model`: string
  - `default_base_url`: opcional
  - `notes`: string corta
- Función pura `list_known_models(role: str | None) -> list[dict]`
- CLI: `filewizard perception models` imprime la tabla (sin red).
- UI Ajustes (opcional si cabe sin rediseño grande): combo o botón “Rellenar defaults de…” que **solo** rellena campos, no arranca servers.

**Errors**

- Role desconocido → `ValueError` o Click error claro.

### Archivos esperados

- `src/filewizard/perception/catalog.py` (nuevo)
- `src/filewizard/cli.py` (subcommand)
- `src/filewizard/ui/settings_dialog.py` (mínimo viable)
- `tests/test_catalog.py` (nuevo)
- `docs/USER_MANUAL.md` (1 párrafo CLI)
- `perception.example.yaml` (comentario con 2–3 modelos del catálogo)

### Tests mínimos

1. Catálogo contiene al menos GLM-OCR, Qwen3-VL-2B, CLIP default zeroshot.
2. `list_known_models("ocr")` no devuelve entradas vision.
3. Role inválido falla de forma explícita.

### Fuera de scope

- Descargar GGUF.
- Nuevo provider HTTP.
- Cambiar defaults de `recommended` sin necesidad.

### Done when

DoD §A + comando CLI documentado.

---

## WP-0.5.2 — `cascade_stage_max` condition

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P1 |
| **Estimación** | S |

### Objetivo

Permitir reglas del tipo “solo si se resolvió sin llegar al VLM” (`stage_used <= N`).

### I/O contract

**In** — `Condition.cascade_stage_max: int | None`  
**Out** — engine check `cascade_stage_max` comparando `features["cascade"]["stage_used"]`  
**Error** — si no hay features cascade → check failed (como otras cascade_*)

### Archivos

- `src/filewizard/models.py`
- `src/filewizard/engine.py` (`_has_any_condition` + `_check_cascade`)
- `tests/test_engine.py`
- `docs/USER_MANUAL.md` §5.5 (una fila en la tabla)
- `rules.example.yaml` (comentario o regla ejemplo opcional)

### Tests

1. `stage_used=1`, `cascade_stage_max=1` → match.
2. `stage_used=3`, `cascade_stage_max=1` → no match.
3. Sin cascade features → no match.

### Fuera de scope

- UI wizard field (YAML/presets bastan).

---

## WP-0.5.3 — Agent-supplied labels (features inject) sin MCP aún

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P0 (desbloquea 0.7) |
| **Estimación** | M |

### Objetivo

Permitir inyectar evidencia `vision` / `ocr` / tags **desde fuera** (CLI JSON o API Python) para que un agente con visión no necesite VLM local. Misma forma de features que produce la cascada.

### I/O contract

**In**

- Archivo JSON o dict:
  ```json
  {
    "/abs/path/to/file.jpg": {
      "vision": {"invoice": 0.91, "document": 0.8, "provider": "agent"},
      "ocr": {"text": "Factura …", "provider": "agent"},
      "cascade": {
        "stage_used": 0,
        "category": "factura",
        "confidence": 0.91,
        "status": "confirmed"
      }
    }
  }
  ```

**Out**

- `src/filewizard/perception/inject.py`:
  - `load_agent_features(path: Path) -> dict[str, dict]`
  - `AgentFeaturesExtractor(mapping)` implementa `FeatureExtractor` (`name="agent_inject"`): `extract(path)` devuelve mapping.get(str(path)) or {}.
- Factory o CLI flag:  
  `filewizard run ... --agent-features path.json`  
  que **antepone** o **fusiona** este extractor (merge: agent keys ganan sobre vacíos; documentar orden).
- Pipeline: sin cambios de firma obligatorios si el extractor se pasa por `default_extractors` / workers.

**Errors**

- JSON inválido → error claro al cargar.
- Paths relativos: resolver respecto a CWD y documentar.

### Archivos

- `perception/inject.py` (nuevo)
- `pipeline.py` o `cli.py` + `ui/workers.py` solo si se expone en UI (CLI basta en este WP)
- `tests/test_agent_inject.py`
- `docs/USER_MANUAL.md` + mención en ROADMAP MCP

### Tests

1. Injector devuelve features para path conocido.
2. Path desconocido → `{}`.
3. Engine rule con `vision_label_gt` / `cascade_category_any` matchea con features inyectadas **sin** HTTP.
4. JSON malo → excepción tipada o `RulesLoadError`-like.

### Fuera de scope

- Servidor MCP (eso es 0.7).
- Entrenar umbrales desde review queue.

### Nota de diseño (arquitecto)

Fusión recomendada en `collect_facts`: extractors en orden; `dict.update` ya hace last-wins.  
Colocar `AgentFeaturesExtractor` **después** de cascade si se quiere override de agente; o **antes** si se quiere short-circuit.  
**Decisión fija para este WP:** agente **después** (override). Documentar en docstring.

---

## WP-0.5.4 — Preset de ejemplo cascade-aware + docs de backends

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P2 |
| **Estimación** | S |

### Objetivo

Añadir preset YAML de ejemplo que use `cascade_*` (no solo filename) y documentar cómo cambiar a Qwen-4B u otro GGUF (solo config).

### Archivos

- `rules/images-cascade-ml.yaml` o `rules_cascade_ml.example.yaml` en root
- `presets` builtin seed si aplica (`presets.py` ensure_builtin)
- `docs/USER_MANUAL.md` workflow
- `README.md` mención breve

### Tests

- Load RuleSet del YAML sin ValidationError.
- Opcional: `ensure_builtin_presets` incluye el nombre si se registra.

### Fuera de scope

- Benchmark real de precisión.

---

## WP-0.5.5 — Release 0.5.0 (chore)

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P0 cierre |
| **Estimación** | S |

### Objetivo

Bump a `0.5.0`, actualizar README / ROADMAP / AGENTS §2, checklist DoD §B.

### No

- Features nuevas en este WP.

---

# Hito 0.6 — Watcher / automatización

**Meta:** vigilar una carpeta y ejecutar un preset en dry-run o execute con journal, sin reimplementar el engine.

---

## WP-0.6.1 — Diseño mínimo en código: `WatchConfig` + CLI dry API

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P0 del hito 0.6 |
| **Estimación** | M |

### Objetivo

Modelo de config y función pura/orquestadora:

```text
watch_once(source, preset|rules, *, dry_run, state_dir, limit) 
  -> plan_operations + optional execute
```

Sin inotify aún: un “tick” invocable (poll manual). CLI:

```bash
filewizard watch --source DIR --preset NAME --once [--execute]
```

### I/O

- Reutiliza `plan_operations` + `Executor`.
- Journal batch igual que run.
- CancelToken opcional.

### Archivos

- `src/filewizard/watch.py` (nuevo)
- `cli.py`
- `tests/test_watch.py`
- USER_MANUAL breve

### Fuera de scope

- Daemon systemd, tray icon, multi-carpeta.

---

## WP-0.6.2 — Polling loop + debounce + pid file

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P1 |
| **Estimación** | M |

### Objetivo

`filewizard watch --interval 30` loop con:

- debounce por mtime/size o set de paths nuevos desde último tick
- archivo pid/lock en state_dir para evitar dos watchers
- log a stdout

### Tests

- Debounce: mismo archivo no re-planifica si no cambió (mock time/files).
- Lock: segunda instancia falla claro.

### Fuera de scope

- inotify nativo (puede ser WP-0.6.3 DEFERRED si no hace falta).

---

## WP-0.6.3 — Presets “activos” (enable list)

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P2 |
| **Estimación** | M |

### Objetivo (WP-0.6.3)

Lista en state_dir `active_watches.yaml`:

```yaml
watches:
  - source: ~/Downloads
    preset: images-cascade
    dry_run: true
    interval_s: 60
```

CLI: `watch list|add|remove|run`.

### Tests

- Roundtrip YAML.
- run aplica un watch.

---

## WP-0.6.4 — Release 0.6.0

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P0 cierre |
| **Estimación** | S |

Bump + docs. Igual que WP-0.5.5.

### Hecho

- `__init__.__version__` y `pyproject.toml` → `0.6.0`
- README: version + sección Watcher/automation (0.6.0) + tabla roadmap
- ROADMAP: 0.6.0 movido a **Hecho**; próximo = 0.7
- AGENTS §2: status table (watch single tick / loop / active watches = Done
  0.6.0), version history, test count 114, módulo `watch.py`, persistence
  entries (`.json` debounce / `.lock` / `active_watches.yaml`), test map
- USER_MANUAL: version + §5.6–5.8 watch subcommands
- DoD §B: sin novedades en schema SQLite ni deps nuevas

---

# Hito 0.7 — MCP server

**Meta:** exponer el **mismo** pipeline por MCP (stdio primero).  
**ADR:** MCP es consumidor; no fork del core. Ver `docs/adr/ADR-0004-mcp-as-pipeline-consumer.md` (Accepted).

---

## WP-0.7.1 — ADR-0004 + esqueleto paquete MCP

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P0 del hito |
| **Estimación** | M |

### Objetivo

- Escribir `docs/adr/ADR-0004-mcp-as-pipeline-consumer.md` — **Done (Accepted)**: structure en el archivo real.
- Paquete `src/filewizard/mcp/` con entrypoint:
  - extra opcional `[mcp]` en pyproject (deps: SDK MCP oficial mínimo necesario).
- Script: `filewizard-mcp` o `filewizard mcp serve`.
- Tool **ping** / `filewizard_version` que devuelve `__version__`.

### Tests

- Import del módulo sin arrancar stdio.
- version tool pure function.

### Fuera de scope

- Todos los tools de golpe (siguientes WPs).

---

## WP-0.7.2 — Tools de lectura: presets, journal batches, collect_facts

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Estimación** | M |

### Tools

| Tool | Maps to |
|------|---------|
| `filewizard_list_presets` | `presets.list_presets` |
| `filewizard_journal_batches` | `Journal.recent_batches` |
| `filewizard_collect_facts` | `collect_facts` (+ extractors opcionales) |

### Invariantes

- Solo lectura; no mutan FS.
- Paths absolutos en respuestas.
- Errores como estructuras JSON `{ok:false, error:…}`.

### Tests

- Unit de handlers con tmp_path (sin stdio real si es pesado).

---

## WP-0.7.3 — Tools de plan / execute / undo

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Estimación** | L |

### Tools

| Tool | Comportamiento |
|------|----------------|
| `filewizard_plan` | dry-run `plan_operations`; devuelve ops resumidas + explanations |
| `filewizard_execute` | **requiere** `confirm=true`; si no, error |
| `filewizard_undo_batch` | undo por `batch_id`; dry-run default; apply solo `confirm is True` |

### Invariantes

- Execute **nunca** implícito.
- Mismo journal que CLI.
- Límite `limit` obligatorio o default bajo (p.ej. 100) para plan.

### Tests

- Plan no mueve archivos.
- Execute sin confirm falla.
- Execute+confirm mueve + journal row.
- Undo batch.

---

## WP-0.7.4 — `filewizard_apply_agent_labels` + cable a inject

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` (audit Grok APPROVE 2026-08-11) |
| **Estimación** | M |

### Objetivo

Tool MCP que escribe/mergea labels en el formato de WP-0.5.3 y opcionalmente lanza plan.

Reutilizar `perception/inject.py`.

---

## WP-0.7.5 — Docs MCP + release 0.7.0

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` (audit Grok APPROVE 2026-08-11; hito 0.7 SHIPPED) |
| **Estimación** | S |

### Objetivo

- USER_MANUAL sección MCP (tools, confirm, install `[mcp]`)
- ROADMAP / README: 0.7.0 en Hecho
- AGENTS §2 + version bump `__init__` + `pyproject` → **0.7.0**
- Ejemplo config Claude/Cursor (stdio: `filewizard mcp serve` / `filewizard-mcp`)
- No features nuevas (chore de release)

---

# Hito 0.8 — Lo shipped se entiende y se usa

**Meta:** corregir huecos P0 y hacer visibles en GUI/MCP las capacidades 0.4–0.7.  
**No es:** backends NPU/4B, Flatpak, inotify.  
**Diseño:** [AUDIT_0.8.md](./AUDIT_0.8.md)  
**Version bump:** `0.8.0` en WP-0.8.8.

---

## WP-0.8.1 — MCP plan/execute usan percepción del state_dir

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P0 (F1) |
| **Estimación** | M |

### Objetivo

`filewizard_plan` y `filewizard_execute` deben usar `default_extractors(state_dir=…)` (más `agent_features` si se pasan), **no** `extractors=()`.

### I/O

- In: mismos args + opcional `perception_profile`, `enable_ocr`, `enable_vision`.
- Out: ops pueden incluir `perception` snapshot; reglas `cascade_*` pueden matchear stage 0 sin HTTP.
- Confirm gate **sin cambios** (`confirm is True`).
- Plan sigue `Journal(":memory:")` + `dry_run=True`.

### Tests

1. Plan con regla `cascade_category_any` + imagen `Screenshot_*.png` → ≥1 op **sin** llama-server.
2. Plan con `extractors` implícitos no mueve archivos.
3. Execute sigue exigiendo `confirm is True`.

### Fuera de scope

- Semáforo HTTP; zeroshot obligatorio.

---

## WP-0.8.2 — Bug categoría factura stage 2 + `only_paths` resolve

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P0 (F2, F3) |
| **Estimación** | S |

### Objetivo

1. En `cascade.py` stage 2: categoría = hint semántico (`recibo`/`factura`/`documento_escaneado`), **no** `if status` truthy → siempre factura.
2. `plan_operations`: comparar `path.resolve()` con `{p.resolve() for p in only_paths}`.

### Tests

- OCR text con “recibo” + hint recibo → category `recibo` (no `factura`).
- `only_paths` con path no resuelto vs iter_files resuelto → aún planifica.

---

## WP-0.8.3 — Home: badge cola + intent cascade-ML + menos ruido

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P1 (F4, F5, F12) |
| **Estimación** | M |

### Objetivo

- Badge/count en **Cola de revisión…** (`ReviewQueue.pending()`).
- Intent home: **Organizar imágenes (cascada + percepción)** → `preset_name=images-cascade-ml`.
- Tras preview, status del wizard: “N archivos en cola de revisión” si aplica.
- No rediseñar todo el home; grid sigue 2 columnas.

### Fuera de scope

- Drag-drop; theming.

---

## WP-0.8.4 — Mostrar evidencia (journal + preview)

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P1 (F9) |
| **Estimación** | M |

### Objetivo

- Historial: al expandir un lote, fila secundaria o tooltip con `perception` (category, stage, status, confidence) si existe.
- `PreviewDialog`: si hay `PlannedOperation.perception` o facts.cascade, mostrar 3–4 líneas de evidencia.
- Reutilizar `Journal.parse_perception` / `perception_snapshot`.

### Tests

- Parse + helper de formato (unit, sin display). GUI opcional.

Absorbe **WP-P.1**.

---

## WP-0.8.5 — Cola de revisión usable

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P1 (F10) |
| **Estimación** | M |

### Objetivo

- Thumbnail del path seleccionado (mismo `load_thumbnail` que preview).
- Doble clic abre preview si el archivo existe.
- Tras **Asignar**, el item guarda categoría; botón **Exportar labels JSON** (formato `inject` / MCP) para `--agent-features` o `apply_agent_labels`.
- No auto-retune umbrales.

Absorbe parte de **WP-P.2**.

---

## WP-0.8.6 — Ajustes: scroll + catálogo

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P1 (F8) |
| **Estimación** | M |

### Objetivo

- `QScrollArea` en `PerceptionSettingsDialog`; tamaño mínimo ~640×640.
- Combo “Rellenar desde catálogo…” por rol (`list_known_models`) que **solo** escribe model/URL.
- Texto corto: OCR/visión del wizard vs etapas 2/3 de cascada.

### Fuera de scope

- Descargar GGUF.

---

## WP-0.8.7 — Watch mínimo en GUI

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P1 (F11) |
| **Estimación** | M |

### Objetivo

Grupo en home o diálogo **Vigilancia…**:

- Lista `load_active_watches`.
- Añadir (nombre, source, preset combo, dry-run).
- **Ejecutar tick** (`watch_once`) en QThread + progreso; no loop infinito en UI (el loop sigue siendo CLI).

### Tests

- Roundtrip add/list ya cubierto; worker: mock o unit de `to_watch_config`.

### Fuera de scope

- Polling `--interval` en GUI; tray; systemd.

---

## WP-0.8.8 — Release 0.8.0

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P0 cierre |
| **Estimación** | S |

Bump `__version__` / `pyproject` → **0.8.0**.  
README, ROADMAP, AGENTS §2, USER_MANUAL (home intents, watch UI, evidencia).  
Sin features nuevas.

---

# Cola de bugs / polish (intercalable si el humano prioriza)

| ID | Status | Descripción |
|----|--------|-------------|
| WP-P.1 | subsumido 0.8.4 | Evidencia perception en UI |
| WP-P.2 | subsumido 0.8.5 (parcial) | Cola: export labels; retune umbrales sigue fuera |
| WP-P.3 | subsumido 0.9.4 | Semáforo 1-inflight HTTP (`_HTTP_LOCK` en POST) |
| WP-P.4 | `DEFERRED` | Tests GUI smoke con pytest-qt (opcional) |

---

# Registro de ejecución (rellenar en handoff)

| WP | Implementador | Fecha inicio | Fecha IN_REVIEW | Audit | Fecha DONE |
|----|---------------|--------------|-----------------|-------|------------|
| 0.5.1 | DeepSeek V4 (OpenCode) | 2026-08-11 | 2026-08-11 | APPROVE (Grok) | 2026-08-11 |
| 0.5.2 | DeepSeek V4 (OpenCode) + architect test/doc polish | 2026-08-11 | 2026-08-11 (×2 handoffs) | APPROVE (Grok) re-confirmed | 2026-08-11 |
| 0.5.3 | DeepSeek V4 (OpenCode) | 2026-08-11 | 2026-08-11 | APPROVE (Grok) | 2026-08-11 |
| 0.5.4 | DeepSeek V4 (OpenCode) | 2026-08-11 | 2026-08-11 | APPROVE (Grok) | 2026-08-11 |
| 0.5.5 | DeepSeek V4 (OpenCode) | 2026-08-11 | 2026-08-11 | APPROVE (Grok); human early-ok | 2026-08-11 |
| 0.6.1 | DeepSeek V4 (OpenCode, AFK) | 2026-08-11 | 2026-08-11 | APPROVE (Grok) | 2026-08-11 |
| 0.6.2 | DeepSeek V4 (OpenCode, AFK) | 2026-08-11 | 2026-08-11 | APPROVE (Grok) | 2026-08-11 |
| 0.6.3 | DeepSeek V4 (OpenCode, AFK) | 2026-08-11 | 2026-08-11 | APPROVE (Grok) | 2026-08-11 |
| 0.6.4 | DeepSeek V4 (OpenCode, AFK) | 2026-08-11 | 2026-08-11 | APPROVE (Grok) | 2026-08-11 |
| 0.7.1 | DeepSeek V4 (OpenCode, AFK) | 2026-08-11 | 2026-08-11 | APPROVE (Grok) | 2026-08-11 |
| 0.7.2 | DeepSeek V4 (OpenCode, AFK) | 2026-08-11 | 2026-08-11 | APPROVE (Grok) | 2026-08-11 |
| 0.7.3 | DeepSeek V4 (OpenCode, AFK) + architect confirm-gate fix | 2026-08-11 | 2026-08-11 | APPROVE (Grok) | 2026-08-11 |
| 0.7.4 | DeepSeek V4 (OpenCode, AFK) | 2026-08-11 | 2026-08-11 | APPROVE (Grok) | 2026-08-11 |
| 0.7.5 | DeepSeek V4 (OpenCode, AFK) | 2026-08-11 | 2026-08-11 | APPROVE (Grok) — hito 0.7 SHIPPED | 2026-08-11 |
| 0.8.1–0.8.8 | Grok (architect implement) | 2026-08-13 | 2026-08-13 | self-audit | 2026-08-13 |
| 0.9.1–0.9.3 | Grok (architect implement) | 2026-08-13 | 2026-08-13 | self-audit | 2026-08-13 |
| 0.9.4 | DeepSeek V4 (OpenCode) + architect HTTP acquire timeout | 2026-09-04 | 2026-09-04 | APPROVE (Grok) | 2026-09-04 |
| 0.9.5 | DeepSeek V4 (OpenCode) + architect env-first roots | 2026-09-04 | 2026-09-04 | APPROVE (Grok) | 2026-09-04 |
| 0.9.6 | DeepSeek V4 (OpenCode) + architect DoD B docs | 2026-09-04 | 2026-09-04 | APPROVE (Grok) | 2026-09-04 |
| 0.9.7 | DeepSeek V4 (OpenCode) | 2026-09-05 | 2026-09-05 | pendiente | — |

---

# Hito 0.9 — Endurecimiento runtime — SHIPPED 0.9.0

**Meta:** H1–H5 (progreso, hilo watch, cola corrupta, sleep cancelable). HTTP/logs/MCP roots = WP-0.9.4+.  
**Diseño:** [AUDIT_0.9.md](./AUDIT_0.9.md)

## WP-0.9.1 — Executor progress on all continues — DONE (H2)

## WP-0.9.2 — Watch tick QThread + interruptible_sleep — DONE (H1, H5)

## WP-0.9.3 — ReviewQueue corrupt load — DONE (H3)

## WP-0.9.4 — HTTP 1-inflight + file logging — DONE (H4, H9, H6)

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P1 (H4, H9) |

Lock en `chat_completion_with_image` (POST only; `probe_server` libre; acquire timeout `timeout_s+5`). GUI: rotating log `state_dir/filewizard.log`. No loguear OCR/base64.
Extra: WAL + busy_timeout, cache cap 64MiB, warn en fallback CLIP, closeEvent en watch/preview dialogs. Tests: `tests/test_runtime_09.py` (5).

## WP-0.9.5 — MCP allowed_roots + CLI pending warn — DONE (H8, H14)

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |
| **Prioridad** | P1 (H8, H14) |

Si `mcp.allowed_roots` o env `FILEWIZARD_SOURCE_ROOT` está set, `source` de execute/plan debe quedar debajo. CLI avisa journal `pending` al arrancar.
Implementado: jail de source (plan/execute/apply_labels) + jail de destino (plan marca op error, execute la salta); `confirm=true` no salta el jail; env gana sobre yaml (sin merge). Tests: `tests/test_mcp_roots_09.py` (7). Docs: USER_MANUAL §5.12.

## WP-0.9.6 — Release 0.9.0 — DONE

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` |

Tras 0.9.4–0.9.5. Bump + CHANGELOG.
Hecho: `__version__` + pyproject → 0.9.0; CHANGELOG; AGENTS; ROADMAP 0.9 shipped; README + RELEASE.md. Sin features nuevas.

---

## WP-0.9.7 — Afilado de Reglas y Templates — DONE (self-audit APPROVE)

| Campo | Valor |
|-------|--------|
| **Status** | `IN_REVIEW` (implementado; espera audit) |
| **Estimación** | M |

Motor: `not_filename_pattern_any` + `{cascade_category}` (slug, fallback `uncategorized`). Presets: regla WA explícita + exclusión en cámara, OCR sin `total`, Misc→Review + fallback final. Wizard: 4 campos (patrón, excluir patrón, EXIF cámara, categoría cascada). Tests: `tests/test_sharpen_09.py` + `test_ui_options.py`.

---

## WP-0.9.8 — Remediación Fase 1 (auditoría integral)

| Campo | Valor |
|-------|--------|
| **Status** | `DONE` (self-audit APPROVE: sin restos, 201 passed) |

C1 invoice-spoof→probable, C2 reverse map canónico, C3 jail en
collect_facts/undo_batch, I1 fallback load_qss. Tests:
`tests/test_remediation_098.py` (5).

---

## WP-0.9.9 — Remediación Fase 2 (auditoría integral) — DONE (self-audit APPROVE, 211 passed, ruff limpio)

| Campo | Valor |
|-------|--------|
| **Status** | `IN_REVIEW` (implementado; espera audit) |

I12 paridad MCP, I11 CI/ruff/pins, I4/I5 cascada+roundtrip, I9 aviso remoto,
I2/I3 foco+confirms, I6 memo cache + batch review. Tests +15 (211 passed),
`ruff check` limpio. Sin bump de versión (batch al próximo release).

---

## WP-0.10.0 — Fase 3 + release 0.10.0 — DONE (self-audit APPROVE, 215 passed, ruff limpio)

Retención/purga journal+review + `purge`; `total` fuera de keywords; SR
(buddy/default/Enter/nombres); multi-select review; versión single-source.
Bump 0.10.0 + CHANGELOG + AGENTS/ROADMAP. Sin tag: no hay repo git.

---

## WP-0.10.1 — Auditoría integral Fase 1 — DONE (self-audit APPROVE, 218 passed, ruff limpio)

C1 screenshot→probable + test spoof; I1 `MCP_LIMIT_MAX=1000` + test;
I3 `save_preset`/export atómicos + test; I13 barrido docs (README/RELEASE/
DoD/BRIEF/USER_MANUAL) + release 0.10.1.

---

# Hito 0.11 — Downloads + cola → labels + escritorio — SHIPPED 0.11.0

## WP-0.11.1 — Preset downloads-docs — DONE
## WP-0.11.2 — Review labels inject — DONE
## WP-0.11.3 — older_than_days / aspect — DONE
## WP-0.11.4 — .desktop + hicolor — DONE
## WP-0.11.5 — Release 0.11.0 — DONE

---

# Prompt sugerido para OpenCode (copiar/pegar)

```text
# Hitos 0.5–0.11 SHIPPED (producto 0.11.0). No hay WP READY.
# 0.12+ lo define el arquitecto. No inventes features.
```

