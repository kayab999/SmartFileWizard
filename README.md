# FileWizard

**Local-first file classification and organization for Linux.** — SmartFileWizard

Build rules (or use a short wizard) to move and rename files safely: preview first, apply second, undo anytime.

> **Perception provides evidence · Rules decide · The journal undoes**

| | |
|--|--|
| **Version** | 0.11.0 |
| **Python** | ≥ 3.11 |
| **License** | MIT ([LICENSE](LICENSE)) |
| **Download** | [Releases](https://github.com/kayab999/SmartFileWizard/releases/latest) — `FileWizard-0.11.0-x86_64.AppImage` |

---

## Why FileWizard?

Typical tools fragment into file managers, photo apps, scripts, and duplicate finders. FileWizard is a **rule engine with a human-friendly shell**:

- Deterministic rules (extension, MIME, name, size, path, cascade category, …)
- Optional perception stack as *evidence only* (heuristics → zero-shot → OCR → VLM)
- Dry-run by default
- SQLite journal with **safe undo** and perception snapshots
- CLI for automation and a PySide6 GUI for everyday use

It is **not** an AI-first product. Intelligence is optional; organization works without models.

**Support:** [Buy Me a Coffee](https://buymeacoffee.com/kayabsoftware) · [GitHub](https://github.com/kayab999/SmartFileWizard) (also **Apoyar…** in the GUI).

---

## Documentation

| Document | For |
|----------|-----|
| **[User Manual](docs/USER_MANUAL.md)** | Install, GUI wizard, CLI, cascade, review queue, troubleshooting |
| **[AGENTS.md](AGENTS.md)** | Architecture, module map, status (all agents) |
| **[Implementer brief](docs/IMPLEMENTER_BRIEF.md)** | **OpenCode / DeepSeek — start here** |
| **[Work plan](docs/WORK_PLAN.md)** | Work packages (0.5–0.9 shipped) |
| **[Changelog](CHANGELOG.md)** | Release history |
| **[Release 0.10.0](docs/RELEASE.md)** | Tag checklist and verify steps |
| **[Roles](docs/ROLES.md)** | Architect (Grok) vs implementer (DeepSeek) |
| **[Definition of Done](docs/DEFINITION_OF_DONE.md)** | WP + release checklist |
| **[ADRs](docs/adr/)** | Architecture decisions |
| **[Robustness charter](docs/ROBUSTNESS.md)** | R1–R15 |
| **[Roadmap](docs/ROADMAP.md)** | Product milestones (next: 0.10+) |
| **[Audit 0.8](docs/AUDIT_0.8.md)** | Architect findings + 0.8 rationale |
| **[Audit 0.9](docs/AUDIT_0.9.md)** | Runtime hardening findings (remediated) |
| **[Cascade plan](docs/PLAN_CASCADE.md)** | Stage 0→3 (done through 0.5.0) |
| **[Perception providers](docs/PLAN_PERCEPTION_PROVIDERS.md)** | HTTP models, profiles |
| `rules.example.yaml` / `rules_sharp.yaml` | Sample rules |
| `rules_cascade_ml.example.yaml` | Cascade-aware preset sample (builtin `images-cascade-ml`) |
| `perception.example.yaml` | Perception + cascade config |

---

## Installation

### Option A — AppImage (recommended, no Python needed)

For most Linux users — one file, double-click to run.

1. Go to **[Releases](https://github.com/kayab999/SmartFileWizard/releases/latest)** and download `FileWizard-0.11.0-x86_64.AppImage`.
2. Make it executable and launch:
   ```bash
   chmod +x FileWizard-*.AppImage
   ./FileWizard-*.AppImage          # GUI — or double-click in your file manager
   ./FileWizard-*.AppImage --help   # CLI — same bundle
   ./FileWizard-*.AppImage run --source ~/Downloads --preset downloads-docs --verbose
   ```
   - On **Ubuntu 24.04+** you may need FUSE first: `sudo apt install libfuse2`.
     Without FUSE, run with: `./FileWizard-*.AppImage --appimage-extract-and-run --help`.
   - User data lives in `~/.local/share/filewizard/` (journal, presets, cache) — the AppImage itself is read-only.
   - The AppImage bundles Python, PySide6, Pillow and the FileWizard engine. Optional perception extras (`tesseract`, `llama-server`, zero-shot `torch`) are **not** bundled — see [Perception](#perception-stack-040--050) and `perception.example.yaml`.

> **Build it yourself:** `bash packaging/appimage/build.sh` → `dist/FileWizard-0.11.0-x86_64.AppImage` (needs `PyInstaller` + `appimagetool`; see [`packaging/appimage/README.md`](packaging/appimage/README.md)).

### Option B — From source (developers / pip)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
```

#### GUI

```bash
filewizard-ui
# or
filewizard ui
```

Home: **¿Qué quieres hacer?** → intent or preset → wizard → **Revisar** → Apply.  
Also: **Ajustes…**, **Cola de revisión…** (badge if pending), **Vigilancia…** (one watch tick).

### CLI

```bash
# Preview (no changes)
filewizard run --source ~/Downloads --rules rules.example.yaml --verbose

# Apply
filewizard run --source ~/Downloads --rules rules.example.yaml --execute

# Preset library
filewizard presets list
filewizard run --source ~/Downloads --preset images-cascade --verbose

# Undo
filewizard undo
filewizard undo --execute
```

### Optional extras

```bash
pip install -e ".[images]"     # image dimensions (Pillow)
pip install -e ".[ocr]"        # Tesseract OCR (+ apt install tesseract-ocr)
pip install -e ".[zeroshot]"   # Stage-1 CLIP/SigLIP via transformers (optional)
pip install -e ".[ui]"         # PySide6 GUI
pip install -e ".[mcp]"        # MCP server for agents
```

---

## Architecture (summary)

```text
CLI / GUI / MCP (since 0.7.0)
        │
        ▼
   pipeline.plan_operations
        │
   scanner → facts (+ perception) → engine → executor → journal
                    │
         cascade: 0 heuristics → 1 zeroshot → 2 OCR → 3 VLM
                    │
              features only (never moves files)
```

| Layer | Responsibility |
|-------|----------------|
| `scanner` | Which files to consider |
| `facts` + `perception/` | What we know about each file |
| `engine` | Whether a rule matches (+ structured reasons) |
| `executor` | Plan / dry-run / execute |
| `journal` | How to reverse moves safely (+ perception snapshot) |
| `review_queue` | Manual classification for uncertain cascade outcomes |
| CLI / UI / MCP | Consumers only — **no independent FS logic** |

Full blueprint: **[AGENTS.md](AGENTS.md)**.

---

## Features by version

### Core (0.1.x)

- YAML rules (Pydantic-validated)
- Move / rename with path templates (`{year}`, `{date}`, …)
- Dry-run default, collision policies (`append` / `skip` / `replace`)
- Structured match explanations (`ConditionCheck`)
- Safe undo (size check, no silent overwrite)

### UI (0.2.0)

- Intent-based home screen
- Four-step wizard + dry-run review
- Same journal as CLI (`~/.local/share/filewizard/`)

### Sharpening + robustness (0.3.x)

- Heuristics: EXIF date, filename patterns, palette (`unique_colors`)
- Negations (`not_*`), true-date templates
- Cascaded `rules_sharp.yaml` + **presets library**
- Shared `pipeline` (CLI = UI RuleSet)
- Review grouped by destination; journal **by batch**

### Perception stack (0.4.0 – 0.5.0)

| Version | Delivery |
|---------|----------|
| **0.4.0** | Progress/cancel; HTTP providers (GLM-OCR + Qwen3-VL-2B defaults) |
| **0.4.1** | UI **Ajustes** (URLs / models / profiles) |
| **0.4.2** | **Cascade** cheap-first (`CascadeExtractor` + thresholds) |
| **0.4.3** | Stage-1 **zero-shot** (`[zeroshot]`); `cascade_*` conditions; **review queue** UI |
| **0.4.4** | Disk **cache** by content hash; journal column `perception` (compact snapshot) |
| **0.5.0** | Model **catalog** + `perception models` CLI · `cascade_stage_max` condition · **agent feature inject** (`--agent-features`) · cascade-aware preset `images-cascade-ml` |

#### Cascade (profile `recommended`)

```text
Stage 0  Heuristics (filename patterns, palette)     ~ms
Stage 1  Zero-shot CLIP/SigLIP (optional extra)      if installed
Stage 2  OCR (GLM-OCR :8080 or Tesseract)            if not confirmed
Stage 3  VLM JSON (Qwen3-VL :8081)                   if still uncertain
```

```bash
filewizard perception init --profile recommended
# Terminal A/B — user-installed llama-server
llama-server -hf ggml-org/GLM-OCR-GGUF:Q8_0 --port 8080
llama-server -hf <qwen3-vl-2b-gguf> --port 8081

filewizard perception status
filewizard perception test ./invoice.png --profile recommended

filewizard run --source ~/Downloads --preset images-cascade \
  --perception-profile recommended --limit 50 --verbose
```

Config: `~/.local/share/filewizard/perception.yaml` (see `perception.example.yaml`).

Try the cascade-aware preset: `filewizard run --source ~/Downloads --preset images-cascade-ml --perception-profile recommended --verbose` (rules in `rules_cascade_ml.example.yaml`).

#### Cascade rule conditions (YAML)

```yaml
when:
  cascade_category_any: [factura, recibo]
  cascade_status_any: [confirmed, probable]
  cascade_min_confidence: 0.75
  cascade_stage_max: 2   # only if resolved before/at stage 2 (0.5.0)
```

Agent-supplied evidence (0.5.0): `filewizard run --agent-features labels.json`
injects precomputed `vision`/`ocr`/`cascade` features from an external AI
(no local VLM needed) — runs after the cascade, overriding it.

#### Review queue

Uncertain outcomes (`unknown` / `rejected` / low-confidence `probable`) are enqueued during wizard preview. Resolve from home → **Cola de revisión…** (badge, thumbnail, export JSON labels for `--agent-features` / MCP).  
Store: `~/.local/share/filewizard/review_queue.json`.

#### Cache & journal snapshot

- Cache dir: `~/.local/share/filewizard/perception_cache/` (toggle in Ajustes)
- On execute, each move may store compact `operations.perception` JSON (stage, category, OCR preview, …)

### Watcher / automation (0.6.0)

| Component | Delivery |
|-----------|----------|
| `watch once` | Single tick: scan folder, plan/apply a preset or rules file |
| `watch --interval` | Polling loop (0.6.2) |
| Debounce | Only changed files re-plan; state in `watch_state.json` |
| Single-watcher guard | pid lock `watch.lock`; stale locks reclaimed |
| `watch add/list/remove/run` | Enable list in `active_watches.yaml` (0.6.3) |
| `only_paths` | Pipeline filter so watcher ticks skip untouched files |

```bash
filewizard watch once --source ~/Downloads --preset images-cascade
filewizard watch add --name DL --source ~/Downloads --preset images-cascade
filewizard watch list && filewizard watch run DL
```

Dry-run by default; `--execute` to apply (journal + undo as always).  
GUI: **Vigilancia…** runs a single tick of a saved watch (loop stays CLI).

### MCP server for agents (0.7.0 – 0.9.0)

The same pipeline is exposed over the Model Context Protocol (stdio) for
Claude / Cursor / other agent clients.

```bash
pip install -e ".[mcp]"
filewizard mcp serve        # or: filewizard-mcp
```

Config example (`"mcpServers": { "filewizard": { "command": "filewizard",
"args": ["mcp", "serve"] } }`).

**9 tools:** `ping`, `filewizard_version`, `filewizard_list_presets`,
`filewizard_journal_batches`, `filewizard_collect_facts`, `filewizard_plan`,
`filewizard_execute`, `filewizard_undo_batch`, `filewizard_apply_agent_labels`.

Safety: `filewizard_execute` and `filewizard_undo_batch` **require
`confirm=true` exactly** (any other value is rejected); `filewizard_plan` and
`filewizard_apply_agent_labels` are dry-run only and never touch the FS.  
**0.8.0:** plan/execute load the same perception stack as CLI (`perception.yaml` / profile).  
**0.9.0:** optional MCP jail via `FILEWIZARD_SOURCE_ROOT` or
`<state_dir>/mcp.yaml` (`allowed_roots`; unset = same power as CLI;
`confirm=true` does not bypass).  
The same journal is used as CLI/GUI, so undo works across all surfaces.

---

## System requirements

| | AppImage | From source |
|--|----------|-------------|
| OS | Ubuntu 22.04+, Debian 12+, Fedora 40+ (x86_64) | Same |
| FUSE | `libfuse2` for double-click (`sudo apt install libfuse2` on 24.04), or use `--appimage-extract-and-run` | Not needed |
| Python | Not needed | 3.11+ |
| Optional | `tesseract-ocr`, `llama-server` for perception | Same + `Pillow`, `PySide6`, `torch` for zero-shot |

**Known limitations:** AppImage is x86_64 only, ~140–180 MB (PySide6). No bundled LLM weights — configure `~/.local/share/filewizard/perception.yaml` (see `perception.example.yaml`). Single-instance not enforced yet (two AppImages = two windows).

## Development

### From source

```bash
pip install -e ".[dev,ui]"
pytest -q
```

### Building the AppImage

```bash
bash packaging/appimage/build.sh          # needs PyInstaller + appimagetool
ls -lh dist/FileWizard-0.11.0-x86_64.AppImage
./dist/FileWizard-*.AppImage --help
```

Reproducible steps + CI: [`packaging/appimage/README.md`](packaging/appimage/README.md) and `.github/workflows/release.yml`.

Expect **224** unit tests (core needs no display).

```text
src/filewizard/          # core + perception/ + plugins/ + ui/
packaging/appimage/      # PyInstaller spec + AppRun + build.sh
tests/
docs/
AGENTS.md
```

---

## Roadmap

See **[docs/ROADMAP.md](docs/ROADMAP.md)**.

| Version | Focus |
|---------|--------|
| **0.5** | Model catalog, `cascade_stage_max`, agent feature inject, cascade-ML preset |
| **0.6** | Folder watch / automation + active presets (`watch once/loop/list/add/remove/run`) |
| **0.7** | **Shipped:** MCP server — 9 tools over stdio; plan/execute/undo + agent labels (confirm-gated) |
| **0.8** | **Shipped:** MCP uses perception; UX (badge, evidence, watch, catalog, review export) |
| **0.9+** | Extra backends, daemon/inotify | 
| **0.11** | **Shipped:** AppImage (`FileWizard-0.11.0-x86_64.AppImage`), `.desktop` + hicolor icon |

---

## Project principle

**The AI (when present) perceives. The rules decide. The journal undoes.**

That separation is intentional and should be preserved in future work.
