# Changelog

All notable product versions. Format: Keep a Changelog (keep it short).

## [Unreleased]

### Added

- GUI **Apoyar…** (home + tray): Buy Me a Coffee and GitHub.

## [0.11.0] — 2026-09-15

Downloads coverage, review labels on next plan, extra predicates, desktop icon + AppImage.

### Added

- Builtin preset `downloads-docs` (PDF, office, archives, video, audio) + home intent.
- Resolved review-queue labels persist to `review_labels.json` and inject on the next plan (after cascade).
- Conditions `older_than_days`, `min_aspect`, `max_aspect`.
- `packaging/filewizard.desktop` + `install-desktop.sh` (user-local hicolor icon).
- **AppImage** `FileWizard-0.11.0-x86_64.AppImage` — PyInstaller one-dir + `appimagetool` (`packaging/appimage/`); double-click GUI, CLI via same bundle (`--help` dispatch); `LICENSE` (MIT); `release.yml` tag workflow.
- **.deb** `filewizard_0.11.0_amd64.deb` — `nfpm` from same `dist/FileWizard` (`/opt/filewizard` + `/usr/bin` shims + desktop/icon, XDG state preserved); `packaging/nfpm.yaml` + `packaging/deb/build-deb.sh`; release workflow builds + smokes + uploads `.deb`.

### Changed

- Desktop file adds `Keywords` + `StartupWMClass`; install script validates and documents AppImage self-containment.
- `README` + `USER_MANUAL` gain AppImage + `.deb` install sections; `docs/RELEASE.md` documents both build outputs.

### Tests

- 224 unit tests.

## [0.10.1] — 2026-09-06

Integral audit Fase 1 (self-audited). No new backends.

### Fixed

- Stage-0 `screenshot` filename pattern yields `probable` (spoof parity
  with the invoice fix).
- MCP `limit` capped at 1000 (`MCP_LIMIT_MAX`) to bound scan/HTTP/payload.
- `presets.save_preset` and review export write atomically (no truncated
  files on crash).
- Release docs match the tree (README/RELEASE/DoD/BRIEF/version 0.10.x).

## [0.10.0] — 2026-09-05

Remediation phases 1–2 + sharpening (self-audited). Behavior changes noted.

### Changed

- Stage-0 filename `invoice` pattern yields `probable` (spoof no longer
  confirms); single `total` OCR hit is `rejected`; stage-2 confidence scales
  with evidence; `medium_confidence` gates VLM.
- `INVOICE_KEYWORDS` drops `total`.
- Review `resolve()` sets confidence 1.0; export skips unresolved `unknown`
  and synthesizes `vision` scores.
- MCP jail extended to `collect_facts`/`undo_batch`; plan/execute carry
  `warnings`; wrappers forward `agent_features`; ops include `perception`.
- Watch tick requires a selection; review supports multi-select triage.
- Version is single-sourced (`filewizard.__version__`).

### Added

- `{cascade_category}` template variable; `not_filename_pattern_any`.
- `filewizard purge` (journal retention) + review `delete()`/`purge_resolved()`.
- Remote-endpoint warnings (CLI/MCP/wizard banner); GUI log file.
- CI matrix 3.11–3.13 + ruff; `requirements-lock.txt`.

## [Unreleased]

### Fase 2 (auditoría integral)

- MCP `filewizard_plan`/`filewizard_execute` aceptan y reenvían
  `agent_features`; las operaciones MCP incluyen el snapshot `perception`.
- CI: matriz Python 3.11–3.13 + job `ruff check`; snapshot
  `requirements-lock.txt`; `ruff` limpio en `src/` y `tests/`.
- Cascada: `medium_confidence` gobierna el paso a VLM; `total` solo ya no
  es `probable`; confianza de etapa 2 proporcional a la evidencia.
- `default_extractors` normaliza mappings dict (claves relativas/CWD ya no
  fallan en silencio); review `resolve()` fija confianza 1.0; el export
  omite `unknown` sin resolver y sintetiza `vision`.
- Aviso de endpoint remoto en CLI (`run`, `watch once`, `perception test`),
  campo `warnings` en plan/execute MCP y banner persistente en el wizard.
- Foco de teclado visible (QSS `:focus`); confirm en limpiar resueltos,
  quitar watch y sobrescribir preset; tick exige selección.
- Cache: memo `(path, mtime, size)` en proceso; cola de review con guardado
  único por preview (también al cancelar).

### Fixed

- Stage-0 filename `invoice` pattern now yields `probable` (was `confirmed`):
  renaming a file to `*factura*` no longer auto-confirms without OCR.
- Stage-3 vision→category uses a canonical reverse map (`invoice→factura`,
  `photo→foto_persona`, …) instead of last-wins dict reversal.
- MCP jail extended to `filewizard_collect_facts` and `filewizard_undo_batch`
  (fail-closed, dry-run included); manual updated.
- Missing/corrupt `style.qss` falls back to unstyled Qt instead of aborting
  GUI startup.
- MCP jail yaml is read from the canonical state dir, not the tool-call
  `state_dir` (agent cannot skip `mcp.yaml` by pointing journal elsewhere).
- Unreadable `mcp.yaml` fails closed with a structured error (no silent `[]`).
- JSON/YAML state files use atomic replace (review queue, cache, watch).
- Home review-queue badge shows `(corrupta)` when `load_error` is set.
- GUI/CLI `watch_once` takes `watch.lock` (loop already held it).
- Perception cache stores compact features (OCR text capped) and a 64MiB
  byte budget; CLIP/HF download is opt-in (`allow_model_download`).
- Busy windows offer **Salir de todos modos** instead of a hard close block.
- GUI scan limit default is 100 (0 = all), matching CLI.

### Added

- `filewizard reset` (cache/logs/queue; `--all --yes` wipes the state dir).
- GitHub Actions `pytest -q` on push/PR.
- Accessible names on home intents and wizard buttons.
- Warning when OCR/VLM `base_url` is not loopback.
- Dark QSS theme, splash, window icon, and Linux tray (idle/active/alert).

## [0.9.0] — 2026-09-04

Runtime hardening (AUDIT_0.9.md). No new backends.

### Fixed

- Executor progress now advances on every skip/noop/error path (H2).
- Watch tick runs off the UI thread (`WatchTickWorker`); loop sleep is
  interruptible (H1, H5). Watch/preview dialogs block close while workers run.
- Corrupt review queue is quarantined to `.bak` with `load_error` (H3, R2).

### Added

- HTTP 1-inflight lock around OCR/VLM calls (H4).
- GUI rotating log `state_dir/filewizard.log` (H9; no OCR/base64).
- SQLite WAL + busy timeout; perception cache skips files >64MiB.
- MCP opt-in jail: `FILEWIZARD_SOURCE_ROOT` / `mcp.yaml allowed_roots`
  for plan/execute sources and destinations (H8; confirm never bypasses).
- CLI `run`/`undo` warn on `pending` journal rows (H14).

### Tests

- 163 unit tests (no display required for core).

---

## [0.8.0] — 2026-08-13

Quality + UX release: shipped 0.4–0.7 capabilities are visible and usable.

### Fixed

- MCP `filewizard_plan` / `filewizard_execute` used empty extractors, so `cascade_*` rules never matched without agent labels. They now use `default_extractors(state_dir=…)` (same stack as CLI).
- Cascade stage-2 invoice path treated any non-empty OCR status as `factura` (`or status`). Recibos / scans keep their hint.
- Watcher `only_paths` compared unresolved `Path` objects; now compares `.resolve()`.

### Added (GUI)

- Home intent **Organizar imágenes (cascada + percepción)** (`images-cascade-ml`).
- Review-queue **badge** (`Cola de revisión (N)…`).
- **Vigilancia…**: list/add/remove active watches and run one tick (dry-run default). Loop/`--interval` remains CLI.
- Preview and journal rows show compact cascade evidence (category · status · stage · confidence).
- Review queue: thumbnail, double-click preview, **Exportar labels JSON** (agent/MCP inject shape).
- Settings: `QScrollArea` + catalog **Rellenar campos**.

### Changed

- Wizard OCR/VLM checkboxes describe force-stage vs cascade in Ajustes.
- Preview status mentions pending review-queue count.
- CLI: `filewizard --version`.

### Tests

- 148 unit tests (no display required for core).

---

## [0.7.0] — 2026-08-11

MCP server (stdio): 9 tools. Execute/undo require `confirm=True` (identity, not truthy strings). `apply_agent_labels` is dry-run only.

## [0.6.0] — 2026-08-11

Folder watcher: `watch once`, polling + debounce + pid lock, `active_watches.yaml`.

## [0.5.0] — 2026-08-11

Model catalog, `cascade_stage_max`, `--agent-features`, preset `images-cascade-ml`.

## [0.4.x] — 2026-08

Perception providers, cascade 0→3, zeroshot extra, review queue, disk cache, journal `perception` snapshot.

## [0.3.x]

Heuristics, presets, shared pipeline, batch journal UI.

## [0.2.0]

PySide6 wizard.

## [0.1.x]

Core engine, CLI, dry-run, journal undo.
