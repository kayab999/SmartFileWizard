# FileWizard — Agent Handover & Architecture

**Purpose:** Give any human developer or coding agent enough context to continue work safely without rediscovering the project from scratch.

**Last updated:** 2026-09-15  
**Product version:** `0.11.0`  
**Workspace:** `/home/carlos/file wizard`

### Dual-agent workflow (read this)

| Role | Who | Entry doc |
|------|-----|-----------|
| **Architect / auditor** | Grok | this file + [docs/ROLES.md](docs/ROLES.md) |
| **Implementer** | DeepSeek V4 via OpenCode | **[docs/IMPLEMENTER_BRIEF.md](docs/IMPLEMENTER_BRIEF.md)** first |
| **Work queue** | — | **[docs/WORK_PLAN.md](docs/WORK_PLAN.md)** (0.5–0.11 shipped) |
| **DoD / audit** | both | [docs/DEFINITION_OF_DONE.md](docs/DEFINITION_OF_DONE.md) |
| **ADRs** | architect | [docs/adr/](docs/adr/) |

Implementers execute **one READY work package** at a time; architects design, update the plan, and audit diffs.  
Do **not** invent features from ROADMAP without a WP.

---

## 1. One-paragraph product summary

FileWizard is a **local-first, rule-based file classification and organization engine for Linux**, with an optional **PySide6 wizard UI**. Deterministic rules move/rename files after a dry-run plan; optional OCR/vision/zero-shot only produce *evidence*. A SQLite **journal** enables safe undo and stores compact perception snapshots. Uncertain cascade outcomes go to a **review queue**. The official architectural principle is:

> **Perception provides evidence; rules decide; the journal undoes.**

---

## 2. Development status (handover log)

### 2.1 Status at a glance

| Area | Status | Notes |
|------|--------|-------|
| Core engine (rules, facts, plan/execute) | **Done** | Stable contract for UI/CLI consumers |
| Journal + undo safety | **Done** | Size checks, no silent overwrite, double-undo safe |
| Journal perception snapshot | **Done 0.4.4** | `operations.perception` JSON (compact) |
| Scanner edge cases | **Done** | Symlinks, hidden, permissions, unicode |
| Structured match explanations | **Done** | `ConditionCheck` for GUI/CLI |
| CLI (`run`, `undo`, `ui`, `presets`, `perception`) | **Done** | Dry-run default |
| GUI shell (Home + wizard) | **Done** | Intent + presets + journal batches |
| Heuristics (EXIF/patterns/palette) | **Done** | `plugins/heuristics.py` |
| Negations + true date templates | **Done** | |
| Thumbnail + manual “Mover a…” | **Done** | Review dialog |
| Journal panel + undo in UI | **Done** | By batch |
| RuleSet pipeline CLI↔UI | **Done** | `pipeline.py` |
| Preview grouped by destination | **Done** | |
| Presets persistence | **Done** | Library + CLI + UI |
| Progress + cancel workers | **Done 0.4.0** | `CancelToken` + UI Detener |
| Perception HTTP providers | **Done 0.4.0** | GLM-OCR + Qwen3-VL-2B defaults |
| Perception settings UI | **Done 0.4.1 / 0.8** | Scroll + catalog fill |
| Cascade extractor (0→2→3) | **Done 0.4.2** | Cheap-first; profile `recommended` |
| Zero-shot stage 1 | **Done 0.4.3** | Optional `[zeroshot]`; CLIP via transformers |
| Conditions `cascade_*` | **Done 0.4.3** | category / status / min_confidence |
| Review queue store + UI | **Done 0.4.3 / 0.8** | JSON + badge + thumbnail + export labels |
| Perception disk cache | **Done 0.4.4 / 0.9+** | Content hash + compact features + 64MiB cap |
| Model catalog + CLI | **Done 0.5.0** | `perception/catalog.py` + `filewizard perception models` |
| Condition `cascade_stage_max` | **Done 0.5.0** | `stage_used <= N` (cheap-first rules) |
| Agent feature inject | **Done 0.5.0** | `--agent-features` JSON; runs after cascade (override) |
| Cascade-ML preset | **Done 0.5.0** | Builtin `images-cascade-ml` (`rules_cascade_ml.example.yaml`) |
| Watch single tick | **Done 0.6.0** | `filewizard watch once` (`watch.py` `watch_once`); preset/rules; dry-run |
| Watch polling loop | **Done 0.6.0** | `watch once --interval N`; debounce mtime/size + pid lock |
| Active watches | **Done 0.6.0 / 0.8** | YAML + CLI + GUI **Vigilancia…** (tick) |
| MCP server for agents | **Done 0.7–0.9** | 9 tools; plan/execute use `default_extractors` (0.8); opt-in `allowed_roots` jail (0.9) |
| Extra backends (4B, NPU, …) | **Backlog 0.5+** | Same contract; catalog documents ids only |
| Daemon / folder watch | **Done 0.6.0** | Polling loop; inotify nativo fuera de scope |
| Packaging (Flatpak/AppImage) | **Partial 0.11** | `.desktop` + hicolor icon; Flatpak/AppImage not started |
| Automated GUI tests | **Not started** | Unit tests cover options/core |

### 2.2 Version history

| Version | What shipped |
|---------|----------------|
| **0.1.x** | Core + CLI + journal + hardening |
| **0.2.0** | PySide6 UI wizard |
| **0.3.x** | Heuristics, negations, pipeline, presets, batch journal UI |
| **0.4.0** | Progress/cancel; `perception/` HTTP providers + profiles |
| **0.4.1** | UI Ajustes de percepción |
| **0.4.2** | `CascadeExtractor` + cascade thresholds; `PLAN_CASCADE.md` |
| **0.4.3** | Zero-shot stage 1; `cascade_*` engine conditions; review queue |
| **0.4.4** | Perception cache by hash; journal `perception` column + snapshot |
| **0.5.0** | Model catalog + `perception models` CLI; `cascade_stage_max`; agent feature inject; cascade-ML preset |
| **0.6.0** | Watcher: `watch once` tick; `--interval` polling loop + debounce + pid lock; active watches (`active_watches.yaml` + `watch list\|add\|remove\|run`) |
| **0.7.0** | MCP server (stdio): 9 tools — `ping`, `filewizard_version`, read (presets/journal/facts), `plan`, `execute` (confirm-gated), `undo_batch` (confirm-gated), `apply_agent_labels` |
| **0.8.0** | MCP plan/execute use perception; invoice category fix; home badge + cascade-ML intent; journal/preview evidence; review export; settings catalog; watch tick UI |
| **0.9.0** | Runtime hardening: execute progress on all paths; watch QThread + close guards; corrupt queue → .bak; HTTP 1-inflight; GUI rotating log; WAL; cache cap 64MiB; MCP allowed_roots jail; CLI pending warn |
| **0.10.0** | Remediation + sharpening: invoice-spoof fix, canonical reverse map, jail extendido, paridad MCP, CI/ruff, cascada medium, review roundtrip, aviso remoto, foco/SR, memo cache, retención/purga, single-source |
| **0.10.1** | Audit Fase 1: screenshot spoof→probable; MCP limit cap; atomic presets/export; docs |
| **0.11.0** | Preset downloads-docs; review labels inject on next plan; older_than_days / aspect; Linux .desktop |

### 2.3 Explicit non-goals (do not implement unless asked)

- Cloud sync, accounts, telemetry  
- Shipping vision/LLM weights inside the core package  
- File-manager style dual-pane explorer as the primary UX  
- Silent batch mutation without dry-run/confirm path  
- Letting models move files outside the executor  

### 2.4 Recommended next milestones

```text
0.7   MCP server (stdio; same pipeline; execute requires confirm)  → SHIPPED 0.7.0
0.8   UX + calidad (AUDIT_0.8.md) → SHIPPED 0.8.0
0.9   Runtime hardening (AUDIT_0.9.md) → SHIPPED 0.9.0
0.10  Remediación integral + afilado → SHIPPED 0.10.0 / 0.10.1
0.11  Downloads-docs + cola→labels + desktop → SHIPPED 0.11.0
0.12  Extra backends / daemon / Flatpak
```

**Executable breakdown for DeepSeek:** [docs/WORK_PLAN.md](docs/WORK_PLAN.md)  
**Role split:** [docs/ROLES.md](docs/ROLES.md)

### 2.5 How to verify the tree

```bash
cd "/home/carlos/file wizard"
source .venv/bin/activate
pip install -e ".[dev,ui]"
pytest -q
filewizard --help
# GUI (needs display): filewizard-ui
```

Expect **224** unit tests passing (as of 0.11.0).

---

## 3. Architectural blueprint

### 3.1 Layered system view

```text
┌─────────────────────────────────────────────────────────────┐
│                     Consumers (no FS logic)                   │
│   CLI (cli.py)     GUI (ui/*)     MCP (mcp/)     (daemon 0.8?) │
└─────────────────────────────┬───────────────────────────────┘
                              │ RuleSet + pipeline
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                         CORE ENGINE                           │
│   scanner ──► facts (+ perception) ──► engine ──► executor    │
│                                      │              │         │
│                                      │              ▼         │
│                                      │           journal      │
│                                      ▼                        │
│                              ConditionCheck[]                 │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼──────────────────┐
              ▼               ▼                  ▼
         Metadata      perception/          review_queue
         (always)   cascade 0→1→2→3         (uncertain)
                    + cache + snapshot
```

### 3.2 Data / control flow (one file)

```text
Path
  → scanner yields Path (regular files only)
  → collect_facts(path, extractors) → FileFacts
       extractors may be CachingExtractor(CascadeExtractor(...))
  → optional on_facts (review queue enqueue)
  → Engine.evaluate(facts) → Match(rule, conditions[])
  → Executor.plan(...) → PlannedOperation (+ perception_snapshot)
  → [dry-run ends here]
  → Executor.execute([ops]) → journal rows (move + perception JSON)
  → undo_operations(journal, rows) → reverse moves safely
```

### 3.3 Module map (source of truth)

| Module | Path | Responsibility |
|--------|------|----------------|
| Models | `src/filewizard/models.py` | Pydantic `Condition`, `Action`, `Rule`, `RuleSet` |
| Facts | `src/filewizard/facts.py` | `FileFacts`, `collect_facts`, `FeatureExtractor` |
| Template | `src/filewizard/template.py` | Safe path/filename templates |
| Engine | `src/filewizard/engine.py` | Match rules; `ConditionCheck`; cascade_* checks |
| Executor | `src/filewizard/executor.py` | Plan, execute, collision, undo; `perception` on op |
| Journal | `src/filewizard/journal.py` | SQLite ops log (+ `perception` column) |
| Scanner | `src/filewizard/scanner.py` | Recursive walk; no symlink follow |
| Pipeline | `src/filewizard/pipeline.py` | Shared scan→facts→match→plan; `on_facts` hook |
| Presets | `src/filewizard/presets.py` | RuleSet library under state_dir |
| Review queue | `src/filewizard/review_queue.py` | JSON store for manual classification |
| Cancel | `src/filewizard/cancel.py` | `CancelToken` cooperative cancel |
| CLI | `src/filewizard/cli.py` | `run`, `undo`, `ui`, `presets`, `perception`, `watch` (once/list/add/remove/run) |
| Watcher | `src/filewizard/watch.py` | `WatchConfig`, `watch_once`, `watch_loop`, debounce `watch_state.json`, pid lock, active watches |
| Atomic persist | `src/filewizard/persist.py` | `atomic_write_text` (tmp + replace) for JSON/YAML state |
| Heuristics | `src/filewizard/plugins/heuristics.py` | EXIF, patterns, palette |
| OCR legacy | `src/filewizard/plugins/ocr.py` | Thin / legacy path |
| Vision legacy | `src/filewizard/plugins/vision.py` | Stub / legacy |
| **Perception** | | |
| Config | `perception/config.py` | Profiles, cascade, cache settings |
| Factory | `perception/factory.py` | `build_extractors`, `perception_status` |
| Cascade | `perception/cascade.py` | Stage 0–3 orchestrator |
| Zero-shot | `perception/zeroshot.py` | CLIP/SigLIP optional |
| Cache | `perception/cache.py` | Content-hash disk cache |
| Snapshot | `perception/snapshot.py` | Compact journal evidence |
| HTTP | `perception/http_openai.py` | OpenAI-compatible client + probe |
| Extractors | `perception/extractors.py` | Tesseract / llama_http OCR & vision |
| **UI** | | |
| App / home | `ui/app.py`, `ui/main_window.py` | Entry, splash, QSS, intents, journal cards, review badge |
| Theme / tray | `ui/theme.py`, `ui/style.qss`, `ui/tray.py`, `ui/assets/` | Dark palette, splash/icon, tray idle/active/alert |
| Wizard | `ui/wizard.py` | Pages + preview/apply |
| Workers | `ui/workers.py` | Preview (enqueues review), Execute, Undo |
| Settings | `ui/settings_dialog.py` | Perception / cascade / cache / catalog |
| Review UI | `ui/review_dialog.py` | Manual queue, thumbnail, export JSON |
| Preview | `ui/preview_dialog.py` | Per-file detail + cascade evidence |
| Watch UI | `ui/watch_dialog.py` | Active watches + one tick |

### 3.4 Core contracts (do not break casually)

#### Rule (YAML / Pydantic)

```yaml
when:   # Condition — all specified fields are ANDed
then:   # Action — at least one of move_to | rename
priority: int   # lower first
stop_after_match: bool
```

Cascade condition fields (0.4.3+):

- `cascade_category_any: list[str]`
- `cascade_status_any: list[str]`
- `cascade_min_confidence: float`
- `older_than_days: int` (mtime age)
- `min_aspect` / `max_aspect: float` (width/height)

#### FileFacts

Immutable snapshot: path, size, mime, extension, filename, stem, mtime, is_image, width/height, `features` dict:

```text
features.cascade  → { stage_used, category, confidence, status, stages, ... }
features.vision   → scores + provider metadata (mapped from cascade)
features.ocr      → { text, provider, ... }
features.filename_patterns, date_taken, unique_colors, ...
```

#### ConditionCheck

```python
ConditionCheck(key: str, passed: bool, detail: str)
```

GUI/CLI must render this instead of re-deriving rule logic.

#### PlannedOperation

Statuses: `planned` | `dry-run` | `done` | `skipped` | `noop` | `error`  
Optional: `perception: dict | None` — compact snapshot for journal.

#### Journal move lifecycle

```text
pending → done | failed | skipped
done → undone   # only after successful reverse move
```

Column `perception TEXT` (JSON) optional on each operation (0.4.4+).  
SQLite `PRAGMA journal_mode=WAL` + `busy_timeout=10000` (0.9.4; silent fallback).  
Undo **must** re-read live row status from SQLite.

#### Cascade statuses

| Status | Meaning |
|--------|---------|
| `confirmed` | High confidence; stages stop early when possible |
| `probable` | Usable for rules; may still enter review if conf low |
| `rejected` | Hypothesis failed (e.g. invoice OCR) |
| `unknown` | Needs human or later stage |
| `error` | Stage failure (not cached as success) |

#### Safety invariants

1. Default CLI mode is dry-run (`--execute` required to mutate).  
2. Mid-batch failure does **not** auto-rollback prior successes (use undo).  
3. Undo never overwrites an unexpected file at the original path (`append_unique`).  
4. Undo refuses if journal destination missing or size ≠ recorded `byte_size`.  
5. UI package must not be imported by core modules (optional `[ui]` extra).  
6. Perception only fills `features`; it never moves files.  
7. Weights not bundled; HTTP endpoints / local torch are user-supplied.

### 3.5 UI architecture

```text
MainWindow
  ├── intents + presets + journal tree
  ├── Ajustes… → PerceptionSettingsDialog
  ├── Cola de revisión… → ReviewQueueDialog
  └── WizardDialog
        ├── Source / Conditions / Action / Review
        ├── PreviewWorker  → plan + on_facts → ReviewQueue
        └── ExecuteWorker  → execute planned ops (perception → journal)
```

- Spanish UI strings (product language).  
- Workers off the UI thread; close blocked while worker active.

### 3.6 Persistence locations

| Item | Path |
|------|------|
| Journal | `~/.local/share/filewizard/journal.db` |
| Perception config | `~/.local/share/filewizard/perception.yaml` |
| Presets | `~/.local/share/filewizard/presets/` |
| Review queue | `~/.local/share/filewizard/review_queue.json` |
| Review labels | `~/.local/share/filewizard/review_labels.json` (resolved queue → next plan) |
| Feature cache | `~/.local/share/filewizard/perception_cache/` |
| Watch debounce state | `~/.local/share/filewizard/watch_state.json` |
| Watch pid lock | `~/.local/share/filewizard/watch.lock` |
| Active watches | `~/.local/share/filewizard/active_watches.yaml` |
| GUI log | `~/.local/share/filewizard/filewizard.log` (1MB × 3) |
| MCP jail config | `~/.local/share/filewizard/mcp.yaml` (opt-in `allowed_roots`; tool `state_dir` does not relocate this file) |

### 3.7 Dependencies

| Layer | Required | Optional |
|-------|----------|----------|
| Core | click, pydantic, PyYAML | pillow, pytesseract |
| Zero-shot | — | torch, transformers, pillow (`[zeroshot]`) |
| UI | — | PySide6 |
| MCP | — | `mcp` SDK (`[mcp]`) |
| Dev | pytest | — |

Python **≥ 3.11**. Layout: `src/` package.

---

## 4. Working agreements for agents

### 4.1 Architectural fit rules

1. **Never** put filesystem move/rename logic in `ui/`.  
2. **Never** make vision/OCR/torch required for core import.  
3. Prefer extending `Condition` / `Action` + engine checks over ad-hoc ifs in CLI/UI.  
4. Any new match reason must be a `ConditionCheck` with stable `key`.  
5. Extend tests when changing executor/journal/scanner/cascade behavior.  
6. Keep dry-run default and undo safety when changing execute paths.  
7. Cascade stages stop early on `confirmed`; do not re-introduce dual full-scan for `recommended`.

### 4.2 Evidence gate (behavior changes)

Prefer: failing test → fix → green suite.  
If only user request: implement + add/adjust tests when possible.

### 4.3 Language / style

- Core code and public identifiers: **English**.  
- GUI user-visible strings: **Spanish**.  
- Docs: English OK for agent docs; user manual English with Spanish UI labels noted.

### 4.4 Commands cheat sheet

```bash
pytest -q

filewizard run --source ~/Downloads --rules rules.example.yaml --verbose
filewizard run --source ~/Downloads --preset images-cascade --execute --yes
filewizard undo --execute --yes

filewizard perception init --profile recommended
filewizard perception status

filewizard-ui
```

---

## 5. Known limitations / tech debt

| Item | Detail |
|------|--------|
| Zero-shot | English-centric prompts; model download on first use; heavy deps |
| Stage-1 batching | Single-image only (no batch GPU queue yet) |
| Review queue | No “use label to retune thresholds” loop yet |
| Journal perception | Compact snapshot only; not full OCR bodies |
| GUI | No automated UI tests; limited drag-drop |
| `Action.tags` | Reserved field, unused |
| Packaging | Editable install only |
| Execute batch | No all-or-nothing transaction (by design: journal + undo) |

---

## 6. Test map

| File | Covers |
|------|--------|
| `tests/test_core.py` | Happy path move, dry-run, undo, templates |
| `tests/test_engine.py` | Conditions, OCR/vision/cascade, priority |
| `tests/test_executor.py` | Collisions, mid-batch, permissions |
| `tests/test_journal_*.py` | Undo safety, batches |
| `tests/test_scanner.py` | Symlinks, hidden, unicode, perms |
| `tests/test_pipeline.py` | Shared plan path |
| `tests/test_presets.py` | Library load/save |
| `tests/test_heuristics_v3.py` | Patterns, EXIF-ish, regex load fail |
| `tests/test_perception.py` | Factory / profiles / HTTP mocks |
| `tests/test_cascade.py` | Stage 0, zeroshot mock, pipeline hook |
| `tests/test_review_queue.py` | Persist, dedupe, filter |
| `tests/test_cache_and_snapshot.py` | Cache hit, fingerprint, journal perception |
| `tests/test_settings_config.py` | Config roundtrip, probe 405 |
| `tests/test_ui_options.py` | `build_rule` helpers (no display) |
| `tests/test_review_grouping.py` | Destination grouping helpers |
| `tests/test_watch.py` | `watch_once`/loop, debounce, pid lock, active watches, once-lock |
| `tests/test_runtime_09.py` | HTTP lock, GUI log, WAL, cache cap, close guards |
| `tests/test_mcp_roots_09.py` | MCP allowed_roots jail, env override, CLI pending warn |
| `tests/test_runtime_09.py` | HTTP lock, GUI log, WAL, cache cap, close guards |
| `tests/test_mcp_roots_09.py` | MCP allowed_roots jail, env override, CLI pending warn |

---

## 7. Documentation index

| Doc | Role |
|-----|------|
| [README.md](README.md) | Project entry, install, quick start |
| [docs/USER_MANUAL.md](docs/USER_MANUAL.md) | End-user guide |
| **AGENTS.md** (this file) | Handover, architecture, status for all agents |
| [docs/ROLES.md](docs/ROLES.md) | Architect vs implementer split |
| [docs/IMPLEMENTER_BRIEF.md](docs/IMPLEMENTER_BRIEF.md) | **OpenCode/DeepSeek entry** |
| [docs/WORK_PLAN.md](docs/WORK_PLAN.md) | Work packages 0.5–0.10 shipped |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [docs/RELEASE.md](docs/RELEASE.md) | release checklist |
| [docs/DEFINITION_OF_DONE.md](docs/DEFINITION_OF_DONE.md) | WP + release checklist |
| [docs/BACKLOG_NOTES.md](docs/BACKLOG_NOTES.md) | Out-of-scope notes from implementer |
| [docs/adr/](docs/adr/) | Architecture decisions |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Product milestones (next 0.10+) |
| [docs/AUDIT_0.8.md](docs/AUDIT_0.8.md) | 0.8 findings (remediated) |
| [docs/AUDIT_0.9.md](docs/AUDIT_0.9.md) | 0.9 runtime findings (remediated) |
| [docs/PLAN_CASCADE.md](docs/PLAN_CASCADE.md) | Cascade design + status |
| [docs/PLAN_PERCEPTION_PROVIDERS.md](docs/PLAN_PERCEPTION_PROVIDERS.md) | Provider contract |
| [docs/ROBUSTNESS.md](docs/ROBUSTNESS.md) | R1–R15 |
| `perception.example.yaml` | Config template |
| `rules.example.yaml` / `rules_sharp.yaml` | Sample rules |

---

## 8. Handover checklist

### 8.1 Any agent (before coding)

1. Confirm version + `pytest -q` baseline.  
2. **Implementer:** open IMPLEMENTER_BRIEF → one READY WP only.  
3. **Architect:** update WORK_PLAN / ADRs; do not silently re-scope WPs mid-flight.  

### 8.2 After a WP (implementer)

1. `pytest -q` green.  
2. Handoff block (ROLES §5).  
3. Mark WP `IN_REVIEW` (not `DONE`).  

### 8.3 Audit (architect)

1. Diff vs WP I/O + DoD.  
2. Verdict APPROVE / REQUEST_CHANGES / REDESIGN.  
3. On APPROVE: WP → `DONE`; update §2 if milestone closed.  

### 8.4 Release

1. Version bump only in dedicated release WP.  
2. README + ROADMAP + AGENTS §2 + USER_MANUAL if UX changed.  
