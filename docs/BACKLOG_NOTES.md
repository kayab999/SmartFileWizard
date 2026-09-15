# Backlog notes (fuera de WP activo)

El **implementador** añade aquí hallazgos que no caben en el WP actual.  
El **arquitecto** los promueve a WORK_PLAN o los descarta.

| Fecha | Autor | Nota | Destino sugerido |
|-------|-------|------|------------------|
| 2026-08-11 | architect | Benchmark real % resueltos stage-1 en carpeta del usuario | WP opcional post-0.5 |
| 2026-08-11 | architect | Review queue: “usar label para retune umbrales” | Post-0.5 UX |
| 2026-08-11 | architect | `cascade_stage_max` condition | Si sale en reglas reales |
| 2026-08-11 | architect | Batch GPU zeroshot | Solo si hay dolor de latencia |
| 2026-08-11 | deepseek | AFK run hito 0.6 completo | **DONE** (audit Grok APPROVE) |
| 2026-08-11 | architect | `ActiveWatch.interval_s` guardado pero no usado por `watch run` (solo tick) | WP polish o 0.6.x+ si se pide loop por nombre |
| 2026-08-11 | architect | `only_paths` comparar siempre con `.resolve()` por robustez | WP-P si hay bug real |
| 2026-08-11 | architect | Flag CLI `--once` redundante (tick es default sin `--interval`) | cosmético |
| | | | |

<!-- Hito 0.6 AFK (DeepSeek) — audit Grok 2026-08-11: APPROVE all DONE -->

### Estado post-audit
- WP-0.6.1 → 0.6.4: **DONE** (producto **0.6.0**).
- **Hito 0.7 MCP SHIPPED (0.7.0)** — WP-0.7.1 … 0.7.5 **DONE**.
- **Hito 0.8 UX SHIPPED (0.8.0)** — remediaciones AUDIT_0.8 P0+P1; 148 tests.
- Polish WP-P.3 / P.4: DEFERRED (HTTP semaphore, pytest-qt).
- Próximo: **0.9+** (ROADMAP) — plan del arquitecto / OK humano.

<!-- Plantilla
| YYYY-MM-DD | deepseek | … | WP-? / descartar |
-->

<!-- Keep local copy -->

---

## Handoff 2026-08-11 — WP-0.7.1 (IN_REVIEW)

```text
WP-ID: WP-0.7.1
Resumen: Esqueleto del MCP server como consumidor de la pipeline (ADR-0004
  Accepted). Paquete src/filewizard/mcp/ con tools ping y filewizard_version +
  entrypoint CLI `filewizard mcp serve` y extra opcional `[mcp]`.
Archivos tocados: src/filewizard/mcp/{__init__,tools,server}.py (nuevo);
  src/filewizard/cli.py (grupo `mcp` + subcomando `serve`);
  pyproject.toml (extra `[mcp]`, script `filewizard-mcp`);
  tests/test_mcp.py (nuevo); docs/adr/ADR-0004 (Accepted), WORK_PLAN.
Tests: pytest -q → 119 passed.
Cómo probar manualmente:
  filewizard mcp serve --help          # SDK opcional, sin arranque
  filewizard mcp serve                 # stdio; hablar por JSON-RPC (e.g. client MCP)
Decisiones tomadas: tools como funciones puras en tools.py (testeables sin SDK);
  version tool devuelve __version__; sin `call_tool` en tests (requiere Context MCP).
Bloqueos / preguntas: ninguna.
```

---

## Handoff 2026-08-11 — WP-0.7.2 (IN_REVIEW)

```text
WP-ID: WP-0.7.2
Resumen: Tools MCP de SOLO lectura sobre el core (ADR-0004): list_presets,
  journal_batches, collect_facts. Handlers puros en tools.py, registrados en
  build_server. Ninguna mutación de FS (journal DB ausente → batches vacío,
  sin crearlo).
Archivos tocados: src/filewizard/mcp/{tools,server,__init__}.py;
  tests/test_mcp_read.py (nuevo); docs/WORK_PLAN, docs/BACKLOG_NOTES.
Tests: pytest -q → 126 passed.
Cómo probar manualmente:
  filewizard mcp serve  # stdio; client MCP → list_tools = 5 tools;
  #   filewizard_list_presets | filewizard_journal_batches | filewizard_collect_facts
Decisiones tomadas: `_state_root` guard para no mkdir presets/journal si dir no
  existe (read-only estricto); paths siempre `.resolve()` absolutos; errores
  uniformes `{ok:false, tool, error}` vía result_error; journal_path de
  vuelta con cada payload.
Bloqueos / preguntas: ninguna.
```

---

## Handoff 2026-08-11 — WP-0.7.3 (IN_REVIEW)

```text
WP-ID: WP-0.7.3
Resumen: Tools de mutación MCP con gate confirm=true estricto (ADR-0004/I1):
  filewizard_plan (dry-run; journal en memoria en vez de on-disk),
  filewizard_execute (confirm=true obligatorio; reusa Executor+Journal del
  core; devuelve batch_id para undo), filewizard_undo_batch (dry-run default;
  undo real solo con confirm=true).
Archivos tocados: src/filewizard/mcp/{tools,server,__init__}.py;
  tests/test_mcp_mutate.py (nuevo; 9 tests); docs/WORK_PLAN, BACKLOG_NOTES.
Tests: pytest -q → 135 passed; smoke e2e client stdio (plan→execute→undo).
Cómo probar manualmente:
  filewizard mcp serve  # 8 tools; plan/execute/undo_batch listados
Decisiones tomadas:
  - plan usa Journal(Path(":memory:")) → cero side effects de FS.
  - batch_id capturado vía journal.recent_batches tras execute (sin tocar core).
  - confirm se evalúa como `confirm is True` literal (JSON booleano).
  - plan/execute usan extractors=() (sin percepción) → deterministas.
Bloqueos / preguntas: ninguna.
```

---

## Handoff 2026-08-11 — WP-0.7.4 (DONE)

```text
WP-ID: WP-0.7.4
Resumen: Tool MCP filewizard_apply_agent_labels que aplica labels de agente
  (formato WP-0.5.3, shape cascade) y opcionalmente lanza un plan dry-run con
  ellas como evidencia. Nunca muta FS (mapping en memoria, journal :memory:).
Archivos tocados: src/filewizard/perception/inject.py (refactor:
  normalize_agent_features extraído como único validador; load_agent_features
  lo reutiliza), src/filewizard/mcp/{tools,server,__init__}.py,
  tests/test_mcp_agent.py (nuevo), tests/test_agent_inject.py OK.
Tests: pytest -q → 144 passed; smoke e2e client stdio (9 tools; labels → plan).
Cómo probar manualmente:
  filewizard mcp serve  # 9 tools; filewizard_apply_agent_labels
Decisiones tomadas:
  - normalize_agent_features en inject.py = source of truth para validar
    labels en memoria (evita duplicar lógica en mcp).
  - extractors usan AgentFeaturesExtractor(mapping); plan con journal :memory:
  - plan opcional solo si `source` + preset|rules.
Bloqueos / preguntas: ninguna.
```

---

## Handoff 2026-08-11 — WP-0.7.5 (DONE)

```text
WP-ID: WP-0.7.5
Resumen: Release chore 0.7.0 — version bump (__init__/pyproject → 0.7.0),
  USER_MANUAL §5.12 MCP (9 tools + confirm-gate + config Claude/Cursor),
  README (sección MCP + roadmap 0.7 shipped), ROADMAP (MCP shipped: tools/
  invariantes/ejemplo config), AGENTS §2/2.4/2.5. Sin features nuevas.
Archivos tocados: src/filewizard/__init__.py, pyproject.toml,
  docs/USER_MANUAL.md, README.md, docs/ROADMAP.md, AGENTS.md,
  docs/WORK_PLAN.md, docs/BACKLOG_NOTES.md.
Tests: pytest -q → 144 passed; filewizard mcp serve --help OK; __version__ = 0.7.0.
Cómo probar manualmente:
  filewizard mcp serve  # 9 tools listados; gate confirm=true en execute/undo
Decisiones tomadas:
  - [mcp] extra y script filewizard-mcp ya existían desde 0.7.1.
  - versión del producto sincronizada __init__ + pyproject (0.7.0).
Bloqueos / preguntas: ninguna.
```

---

## Handoff — WP-0.9.6 (IN_REVIEW)

```text
WP-ID: WP-0.9.6
Resumen: Release 0.9.0 (chore, sin features): bump __version__+pyproject,
  CHANGELOG, AGENTS (versión/historial/tests/docs), ROADMAP 0.9 shipped.
Archivos tocados: src/filewizard/__init__.py, pyproject.toml, CHANGELOG.md,
  AGENTS.md, docs/ROADMAP.md, docs/WORK_PLAN.md.
Tests: pytest -q → 161 passed; __version__ = 0.9.0.
Bloqueos / preguntas: ninguna.
```

## Handoff — WP-0.9.5 (IN_REVIEW)

```text
WP-ID: WP-0.9.5
Resumen: Jail opt-in MCP (H8) + aviso pending en CLI (H14). allowed_roots por
  env FILEWIZARD_SOURCE_ROOT y state_dir/mcp.yaml; source fuera → error
  estructurado antes de planear; destino fuera → op error en plan / skip en
  execute; confirm no bypassa. CLI run/undo avisan pending por stderr.
Archivos tocados: mcp/tools.py (mcp_allowed_roots, _path_within,
  _check_source_root, _apply_destination_jail), cli.py (warn_pending_journal),
  tests/test_mcp_roots_09.py (nuevo, 5), docs/USER_MANUAL.md §5.12.
Tests: pytest -q → 161 passed.
Bloqueos / preguntas: ninguna.
```

## Handoff — WP-0.9.4 (IN_REVIEW)

```text
WP-ID: WP-0.9.4
Resumen: Endurecimiento runtime: lock 1-inflight en chat_completion_with_image,
  filewizard.log rotativo en GUI, WAL+busy_timeout, cache cap 64MiB,
  warn en fallback CLIP, closeEvent en watch/preview.
Archivos tocados: perception/http_openai.py, ui/app.py, journal.py,
  perception/cache.py, perception/zeroshot.py, ui/watch_dialog.py,
  ui/preview_dialog.py, tests/test_runtime_09.py (nuevo).
Tests: pytest -q → 156 passed.
Cómo probar: pytest tests/test_runtime_09.py -q; filewizard-ui (log en state_dir).
Bloqueos / preguntas: ninguna.
```

---

## Handoff — WP-0.9.7 (IN_REVIEW)

```text
WP-ID: WP-0.9.7
Resumen: Afilado de reglas y templates: not_filename_pattern_any en motor,
  {cascade_category} con slug + fallback uncategorized, presets (WA explícita
  + exclusión en cámara, OCR sin "total", Misc→Review + fallback final),
  wizard con 4 campos nuevos. Sin OR, sin VLM→move_to.
Archivos tocados: models.py, engine.py, template.py, rules_sharp.yaml,
  rules.example.yaml, rules_cascade_ml.example.yaml, ui/options.py,
  ui/wizard.py, tests/test_sharpen_09.py (nuevo), tests/test_ui_options.py,
  docs/USER_MANUAL.md, docs/WORK_PLAN.md.
Tests: pytest -q → 192 passed; ConditionsPage offscreen OK.
Cómo probar: dry-run con IMG-*-WA* + cámara + factura; wizard condiciones.
Bloqueos / preguntas: ninguna.
```

---

## Handoff — WP-0.9.7 CLI+MCP parity (IN_REVIEW, amplía 0.9.7)

```text
WP-ID: WP-0.9.7 (parity CLI+MCP)
Resumen: Verificado que CLI y MCP comparten motor/presets/templates.
  MCP plan/execute/apply_agent_labels ahora siembran built-ins como el CLI
  (antes: preset inexistente en state nuevo). Built-ins obsoletos se
  refrescan con presets import --overwrite (documentado, sin auto-sobrescrito).
Archivos tocados: mcp/tools.py (ensure_builtin_presets en plan/execute/apply),
  tests/test_sharpen_09.py (+4: CLI preset WA, CLI refresh, MCP preset WA,
  MCP category template), docs/USER_MANUAL.md.
Tests: pytest -q → 196 passed.
Cómo probar: filewizard run --preset images-cascade (dry-run con WA);
  filewizard_plan preset images-cascade vía MCP.
Bloqueos / preguntas: ninguna.
```

---

## Handoff — WP-0.9.8 Fase 1 (IN_REVIEW)

```text
WP-ID: WP-0.9.8 (Fase 1)
Resumen: C1 invoice stage-0 → probable (spoof por nombre ya no confirma);
  C2 VISION_KEY_TO_LABEL canónico; C3 jail en collect_facts y undo_batch
  (fail-closed incl. dry-run, manual actualizado); I1 load_qss fallback.
  Contrato roto a posta: collect_facts con jail (test viejo actualizado).
Archivos tocados: perception/cascade.py, mcp/tools.py, ui/theme.py,
  tests/test_remediation_098.py (nuevo, 5), tests/test_mcp_roots_09.py,
  docs/USER_MANUAL.md, CHANGELOG.md, docs/WORK_PLAN.md.
Tests: pytest -q → 201 passed.
Nota: invoices-by-cascade permite probable+0.65 — un spoof aún enruta si la
  regla lo admite; es decisión de regla (percepción ahora informa honesto).
  Reglas estrictas: exigir cascade_status_any [confirmed].
Bloqueos / preguntas: ninguna.
```

---

## Handoff — WP-0.9.9 Fase 2 (IN_REVIEW)

```text
WP-ID: WP-0.9.9 (Fase 2)
Resumen: I12 agent_features en wrappers MCP + perception en op;
  I11 matriz 3.11–3.13, job ruff, requirements-lock.txt, ruff limpio;
  I4 medium gobierna VLM + total-solo rejected + confianza proporcional;
  I5 normalización dict + resolve→1.0 + export sin unknown + vision;
  I9 remote_perception_endpoints + warns CLI/MCP + banner wizard;
  I2 anillo :focus; I3 confirms + tick con selección;
  I6 memo (mtime,size) + batch save de review.
Archivos: mcp/{server,tools}.py, .github/workflows/test.yml,
  requirements-lock.txt, perception/{cascade,http_openai,cache}.py,
  pipeline.py, review_queue.py, cli.py, ui/{wizard,style.qss,workers,
  watch_dialog,review_dialog}.py, tests (remediation_098, roots, review,
  cascade, ui_options, mcp, scanner, heuristics).
Tests: pytest -q → 211 passed; ruff check limpio.
Decisiones: pyproject bounds intactos (lock snapshot en vez de pins duros);
  stage_used de resolve se conserva; VLM se salta solo con score>=medium.
Bloqueos / preguntas: ninguna.
```

---

## Handoff — WP-0.10.0 Fase 3 + release (DONE, self-audit APPROVE)

```text
WP-ID: WP-0.10.0
Resumen: Retención (Journal.purge/count_purgeable + CLI purge dry-run default;
  review delete/purge_resolved); total fuera de INVOICE_KEYWORDS; SR
  (buddies, Siguiente default, Enter→preview, ~20 nombres); multi-select en
  review; versión single-source (dynamic attr); release 0.10.0 + docs.
Archivos: journal.py, review_queue.py, cli.py (purge), cascade.py,
  ui/{wizard,review_dialog,watch_dialog,settings_dialog,style.qss,workers}.py,
  pyproject.toml, tests, CHANGELOG, AGENTS, ROADMAP, USER_MANUAL.
Tests: pytest -q → 215 passed; ruff limpio; QSS parsea offscreen.
Self-audit: criterios Fase 3 cumplidos; sin tag (no hay repo git aquí).
Bloqueos / preguntas: ninguna.
```

---

## Handoff — WP-0.10.1 Fase 1 (DONE, self-audit APPROVE)

```text
WP-ID: WP-0.10.1
Resumen: C1 screenshot stage-0 → probable (test spoof dedicado; test viejo
  actualizado); I1 MCP_LIMIT_MAX=1000 + test; I3 save_preset y export labels
  atómicos + test; I13 barrido docs (versión/test-count/DoD B.1/release).
Archivos: perception/cascade.py, mcp/tools.py, presets.py,
  ui/review_dialog.py, tests (remediation_098, cascade), README, RELEASE,
  DoD, BRIEF, USER_MANUAL, AGENTS, ROADMAP, CHANGELOG, WORK_PLAN.
Tests: pytest -q → 218 passed; ruff check limpio; versión 0.10.1.
Self-audit: spoof ya no confirma; cota efectiva; sin .tmp residual;
  grep confirma cero restos 0.9.0/163 en docs vivas.
Bloqueos / preguntas: ninguna.
```

---

## Nota — resources folder (2026-09-13)

```text
Revisado docs/brand/ (masters JPEG mal llamados .png, documentado) y
src/filewizard/ui/assets/ (runtime). Todo válido: app_icon 1024² RGBA,
splash 1024×578, tray 128² RGBA con ~46% píxeles opacos; package-data los
incluye; script regenera idempotente.
Limpieza: eliminado app_icon_256.png muerto (56K, solo lo fijaba un test) +
  su generación y su entrada en test_ui_theme.py.
Tests: 218 passed; ruff limpio.
```
