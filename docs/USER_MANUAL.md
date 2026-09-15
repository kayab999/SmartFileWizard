# FileWizard — User Manual

**Version:** 0.11.0  
**Platform:** Linux (local-first)  
**Audience:** Anyone who wants to organize, rename, or classify files without writing shell scripts.

---

## 1. What is FileWizard?

FileWizard is a **rule-based file organizer**. You describe *which* files to match and *what* to do with them. The app plans the changes, shows a preview, and only then applies them. Everything that was moved can be undone through a journal.

### Design principle

> **Perception provides evidence · Rules decide · The journal undoes**

| Layer | Role |
|-------|------|
| Perception (metadata, cascade, optional OCR/vision) | Describes each file with facts |
| Rules | Decide matches and actions |
| Journal | Records moves so you can reverse them |
| Review queue | Manual category for uncertain cascade outcomes |

FileWizard is **not** primarily an AI app. Intelligence (zero-shot, OCR, VLM) is optional. The product works fully with deterministic rules.

---

## 2. Installation

### Option A — AppImage (for end users, no Python needed)

1. Download `FileWizard-0.11.0-x86_64.AppImage` from **[Releases](https://github.com/kayab999/SmartFileWizard/releases/latest)**.
2. Make executable:
   ```bash
   chmod +x FileWizard-*.AppImage
   ./FileWizard-*.AppImage              # GUI — also double-click in Files
   ./FileWizard-*.AppImage --help       # CLI (same bundle)
   ```
3. Linux integration notes:
   - On **Ubuntu 24.04+** install FUSE for double-click: `sudo apt install libfuse2`.
     Without FUSE: `./FileWizard-*.AppImage --appimage-extract-and-run --help`.
   - AppImage bundles Python + PySide6 + Pillow. Perception extras (Tesseract, `llama-server`, CLIP) remain host-installed and configured in `~/.local/share/filewizard/perception.yaml`.

Build it yourself: `bash packaging/appimage/build.sh` → `dist/FileWizard-0.11.0-x86_64.AppImage` (see `packaging/appimage/README.md`).

### Option B — From source (developers)

#### Requirements

- Linux
- Python **3.11+**
- Optional: Tesseract OCR for local text-in-image rules
- Optional: `llama-server` (or any OpenAI-compatible local endpoint) for GLM-OCR / Qwen
- Optional: desktop environment for the GUI

#### Setup

```bash
cd "/path/to/file wizard"
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
# Optional: app menu + icon (user-local, without AppImage)
bash packaging/install-desktop.sh
```

### Optional extras

| Extra | Install | Purpose |
|-------|---------|---------|
| Images | `pip install -e ".[images]"` | Image width/height (Pillow) |
| OCR | `sudo apt install tesseract-ocr` then `pip install -e ".[ocr]"` | Local Tesseract |
| Zero-shot | `pip install -e ".[zeroshot]"` | Stage-1 CLIP/SigLIP (torch + transformers) |
| UI | `pip install -e ".[ui]"` | PySide6 graphical interface |
| MCP | `pip install -e ".[mcp]"` | Agent server (`filewizard mcp serve`) |

```bash
pip install -e ".[dev,ui,ocr,images,zeroshot,mcp]"
```

---

## 3. Two ways to use FileWizard

| Mode | Command | Best for |
|------|---------|----------|
| **GUI** | `filewizard-ui` or `filewizard ui` | Everyday use, guided wizard |
| **CLI** | `filewizard run` / `undo` / `presets` / `perception` / `watch` / `mcp` / `reset` | Scripts, automation, agents |

Shared state directory:

```text
~/.local/share/filewizard/
  journal.db              # moves + undo + perception snapshots
  perception.yaml         # OCR / vision / cascade / cache
  presets/                # RuleSet library
  review_queue.json       # manual classification queue
  perception_cache/       # feature cache by file hash
  active_watches.yaml     # folder watches (0.6+)
  watch_state.json        # debounce signatures
  watch.lock              # single-watcher pid lock
  filewizard.log          # GUI rotating log (0.9+)
  mcp.yaml                # optional MCP allowed_roots (0.9+)
  review_labels.json      # resolved review categories (next plan, 0.11+)
```

---

## 4. Graphical interface (recommended)

### 4.1 Start the app

```bash
source .venv/bin/activate
filewizard-ui
```

### 4.2 Home screen — “¿Qué quieres hacer?”

| Control | Purpose |
|---------|---------|
| Intent buttons | Prefill wizard (organizar, renombrar, capturas, facturas, …) |
| Biblioteca de presets | Run a saved RuleSet cascade |
| **Cola de revisión…** | Resolve unknown / low-confidence cascade files (badge if pending; export JSON labels) |
| **Vigilancia…** | Active folder watches — add/remove and run one tick |
| **Ajustes…** | Perception: cascade, OCR/VLM URLs, catalog fill, cache |
| **Apoyar…** | Buy Me a Coffee and the GitHub repo |
| Historial de operaciones | Batches; **Deshacer este lote** |

### 4.3 Wizard — four steps

#### Step 1 — Archivos (Files)

| Option | Meaning |
|--------|---------|
| Carpeta origen | Folder to scan (recursive, no symlinks by default) |
| Incluir archivos ocultos | Include hidden files/dirs |
| Activar OCR / visión | Force stage 2/3 when cascade is on (or legacy extractors) |
| Límite de escaneo | Cap how many files to scan (`0` = unlimited) |

While scanning: progress text + **Detener** (cooperative cancel).

#### Step 2 — Condiciones (Conditions)

Match files using one or more filters, **or** check “Todos los archivos”.

| Field | Meaning |
|-------|---------|
| Extensiones | e.g. `jpg, png, pdf` |
| Regex nombre | e.g. `(?i)screenshot\|captura` |
| Ruta contiene | Tokens that must appear in the path |
| OCR contiene | Words that must appear in OCR text |
| Tamaño mayor que | Size threshold in MB |
| Solo imágenes | MIME starts with `image/` |

YAML-only cascade fields (presets / rules files) are listed in §5.9.

#### Step 3 — Acción (Action)

| Field | Meaning |
|-------|---------|
| Mover a | Destination folder (absolute or `~/…`), may use templates |
| Renombrar como | New filename template |
| Crear carpeta destino | Create missing parent directories |
| Colisión | `append` (rename with `_1`), `skip`, or `replace` |

**Template variables:**

| Variable | Example |
|----------|---------|
| `{original_name}` | `photo.jpg` |
| `{stem}` | `photo` |
| `{ext}` | `jpg` |
| `{year}` `{month}` `{day}` | Prefer EXIF / filename date when heuristics find them |
| `{date}` | `2026-08-10` |
| `{datetime}` | `20260810_143022` |

#### Step 4 — Revisar (Review)

1. FileWizard **previews** without moving files.
2. Tree grouped by **destination folder** (counts, expand children).
3. Double-click a row for detail / thumbnail / **Mover a…** override.
4. Confirm **Aplicar** to execute.
5. Optional: open destination folders after apply.

Uncertain cascade files are also written to the **review queue** during preview.

### 4.4 Review queue (Cola de revisión)

Opened from the home screen.

| Status enqueued | When |
|-----------------|------|
| `unknown` | Cascade could not classify |
| `rejected` | OCR validation rejected document hypothesis |
| `probable` + low conf | Confidence under ~0.65 |

Actions: assign category (factura, captura_pantalla, …), dismiss, clear resolved.  
Thumbnail of the selected file; double-click opens preview.  
**Exportar labels JSON…** writes the agent-inject mapping for `--agent-features` or MCP `filewizard_apply_agent_labels`.

The home button shows a **badge** with the pending count.

### 4.5 Ajustes de percepción

| Section | Settings |
|---------|----------|
| Perfil | `lite` / `recommended` / `cascade` / `ocr_only` / `vision_only` |
| Cascada | On/off, high/medium/VLM thresholds, stages 1–3, zero-shot model id |
| Cache | Disk cache of perception features by file hash |
| OCR | Provider (`none` / `tesseract` / `llama_http`), URL, model |
| Visión | Provider (`none` / `llama_http`), URL, model |
| Comprobar endpoints | Probe OCR/VLM servers |
| Catálogo | Pick a known model id and **Rellenar campos** (model/URL only; no download) |

The dialog scrolls. OCR/VLM checkboxes in the wizard *force* stages 2/3; cascade on/off and thresholds live here.

### 4.6 Cambiar de backend (modelo / GGUF)

FileWizard no empaqueta pesos (ADR-0003): solo apuntas `model` / `base_url` en
`perception.yaml` (UI **Ajustes** o `filewizard perception init`).

Para cambiar a otro GGUF (p. ej. Qwen3-VL-4B u OCR más grande):

1. Levanta tu `llama-server` con el GGUF que quieras en el puerto libre que elijas.
2. En **Ajustes → Visión / OCR**, sustituye `model` (y `base_url` si cambia el puerto)
   por los valores de tu servidor.
3. `filewizard perception status` → el endpoint debe aparecer `OK`.
4. `filewizard perception test ./imagen.png --profile recommended` → confirma la salida.

Lista de modelos conocidos (solo informativa, sin descarga): `filewizard perception models`.

### 4.7 Vigilancia (folder watch)

Home → **Vigilancia…**: list saved watches, add (name + folder + preset), remove, **Ejecutar tick**.  
Default is dry-run. Continuous `--interval` polling stays on the CLI (`filewizard watch once --interval 30`).

### 4.8 Look, splash and tray

The GUI uses a dark theme (purple→cyan accents). Startup shows a splash,
then the home window. If the desktop provides a system tray, FileWizard
keeps a tray icon with three states (idle / scanning / review pending).
Closing the window **hides to tray**; **Salir** in the tray menu quits.
If there is no tray, close still quits (same as before).

### 4.9 Safety in the GUI

- Preview never moves files.
- Apply asks for confirmation.
- Closing a busy window offers **Esperar** or **Salir de todos modos**
  (cancels when possible; an in-flight OCR/VLM call may finish its timeout).
- Undo uses the same journal as the CLI (by batch).
- Journal rows may show cascade evidence (category / stage / confidence).

---

## 5. Command-line interface

### 5.1 Rules file (YAML)

Example: `rules.example.yaml` / `rules_sharp.yaml`.

```yaml
version: 1
rules:
  - id: screenshots-by-name
    name: Screenshots por nombre
    priority: 10
    stop_after_match: true
    when:
      mime_prefixes:
        - image/
      filename_regex: "(?i)(screenshot|captura)"
    then:
      move_to: "~/Pictures/Screenshots/{year}/{month}"
      rename: "{date}_{original_name}"
      create_target_dir: true
      on_collision: append
```

**Priority:** lower numbers run first.  
**stop_after_match:** if true, first matching rule wins for that file.

### 5.2 Dry-run (always start here)

```bash
filewizard run \
  --source ~/Downloads \
  --rules rules.example.yaml \
  --verbose
```

Without `--execute`, nothing is moved.

### 5.3 Apply / presets / perception

```bash
# Apply
filewizard run --source ~/Downloads --rules rules.example.yaml --execute --yes

# Presets
filewizard presets list
filewizard presets import rules_sharp.yaml --name images-cascade
filewizard run --source ~/Downloads --preset images-cascade --verbose

# Refresh a builtin after upgrading FileWizard (seeded copies are never
# auto-overwritten, so existing installs keep the old rules until you run):
filewizard presets import rules_sharp.yaml --name images-cascade --overwrite

# Perception
filewizard perception init --profile recommended
filewizard perception status
filewizard perception test ./scan.png --profile recommended
filewizard perception models          # list known models (no network)

filewizard run --source ~/Downloads --preset images-cascade \
  --perception-profile recommended --limit 50 --ocr --verbose

# Runtime cleanup (keeps journal + presets). Package stays installed.
filewizard reset --yes
# Wipe entire ~/.local/share/filewizard (journal, presets, config):
filewizard reset --all --yes
```

`filewizard perception models` prints an informative catalog of known OCR / vision / zero-shot model ids (with default `model` and `base_url`) to help you fill `perception.yaml`; it performs no downloads or network calls.

CLIP/SigLIP weights are **not** downloaded unless **Ajustes → Permitir descarga de pesos CLIP/SigLIP** is checked (`cascade.allow_model_download`). If the model is already in the HuggingFace cache, stage 1 still runs.

| Option | Purpose |
|--------|---------|
| `--limit N` | Scan at most N files |
| `--state-dir PATH` | State root (default `~/.local/share/filewizard`) |
| `--perception-profile` | Built-in profile name |
| `--agent-features PATH` | JSON file with precomputed agent evidence (path → vision/ocr/cascade features) |
| `--ocr` / force vision | Force stage 2/3 when cascade disabled or provider none |
| `--verbose` | Show match explanations |

### 5.4 Agent-supplied features (`--agent-features`)

An AI agent with its own vision can classify images without a local VLM by
writing a JSON file mapping **absolute file paths** to feature dicts (same shape
the cascade produces):

```bash
filewizard run --source ~/Downloads --rules rules.example.yaml \
  --agent-features agent-labels.json --verbose
```

```json
{
  "/home/carlos/Downloads/invoice.jpg": {
    "vision": {"invoice": 0.91, "document": 0.8, "provider": "agent"},
    "ocr": {"text": "Factura 123", "provider": "agent"},
    "cascade": {
      "stage_used": 0, "category": "factura",
      "confidence": 0.91, "status": "confirmed"
    }
  }
}
```

Relative keys are resolved against the current working directory. Agent
evidence runs **after** the cascade, so agent keys override local perception
evidence (last-wins). Rules such as `cascade_category_any` / `vision_label_gt`
match directly on the injected features — no HTTP/GPU needed.

### 5.5 Undo

```bash
filewizard undo              # preview
filewizard undo --execute    # apply
```

**Safe undo behavior:**

- Missing destination → refused (`missing`)
- Size differs from journal → refused (`state_mismatch`)
- Original path occupied → restore with unique name (`done_with_conflict`)
- Double undo → no-op / skipped

**Retention (0.10+):** the journal keeps `done` moves (undo evidence) and
`pending` rows forever. Old `failed`/`skipped`/`error`/`interrupted`/`undone`
rows can be purged:

```bash
filewizard purge                       # preview
filewizard purge --older-than-days 90 --execute
```

Review queue: `Limpiar resueltos` deletes resolved items; single items have no
delete button yet — use `filewizard reset --yes` for a full queue wipe.

### 5.6 Watch (single tick, 0.6.x)

Scan a folder and run a preset or rules file in one tick:

```bash
filewizard watch once --source ~/Downloads --preset images-cascade
filewizard watch once --source ~/Downloads --rules rules.example.yaml --execute --yes
```

- Dry-run by default; add `--execute` to apply (with journal, like `run`).
- Supports the same `--limit`, `--state-dir`, `--perception-profile`,
  `--agent-features`, `--verbose` options as `run`.

### 5.7 Watch polling loop (0.6.2+)

```bash
filewizard watch once --source ~/Downloads --preset images-cascade --interval 30
filewizard watch once --source ~/Downloads --preset images-cascade --interval 30 --execute
```

- Polls the source folder every `--interval` seconds and logs each tick.
- **Debounce:** only files whose mtime or size changed since the last tick are
  re-planned; per-source state is persisted in
  `~/.local/share/filewizard/watch_state.json`, so a restart does not re-plan
  files that have not changed.
- **Single-watcher guard:** a pid lock (`watch.lock`) prevents two watch
  processes from using the same state directory; a second instance fails with
  a clear error. Stale locks from a crashed/killed process are reclaimed
  automatically.
- Stop with **Ctrl-C** (unlike the single tick, there is no confirmation
  step while the loop is running).

### 5.8 Active watches (0.6.3+)

Persist watches in an enable list at `~/.local/share/filewizard/active_watches.yaml`:

```bash
# add a watch (preset OR rules, not both)
filewizard watch add --name Downloads --source ~/Downloads --preset images-cascade
filewizard watch add --name PDFs --source ~/PDFs --rules rules_pdf.yaml --interval 120

# list and run
filewizard watch list           # show enable list
filewizard watch run            # run every active watch once
filewizard watch run Downloads  # run just one watch

# remove
filewizard watch remove Downloads
```

- `--execute` on `add` stores a non-dry-run watch; on `run` it overrides to
  execute for that invocation. Dry-run is the default everywhere.
- The debounce state and single-watcher lock from §5.7 apply to `run` as well.

### 5.9 Condition reference (YAML)

| Field | Type | Description |
|-------|------|-------------|
| `always` | bool | Match every file |
| `extensions` | list | e.g. `["txt", "pdf"]` |
| `mime_prefixes` | list | e.g. `["image/"]` |
| `filename_regex` | string | Regex on filename (invalid regex fails at load) |
| `path_contains` | list | All tokens must appear in path |
| `size_gt` / `size_lt` | int | Size in **bytes** |
| `min_width` / `min_height` | int | Image dimensions (needs Pillow) |
| `ocr_contains_any` / `ocr_contains_all` | list | OCR text |
| `vision_label_gt` | map | e.g. `document: 0.90` (needs vision/cascade features) |
| `filename_pattern_any` | list | Heuristic patterns: `screenshot`, `invoice`, `scan`, … |
| `has_exif_date` / `has_camera_metadata` | bool | Heuristic EXIF flags |
| `exif_software_contains` | list | Software string tokens |
| `min_unique_colors` / `max_unique_colors` | int | Palette heuristic |
| `not_extensions` / `not_filename_regex` / `not_filename_pattern_any` / `not_path_contains` | | Negations (e.g. exclude `whatsapp` from camera rules) |
| `cascade_category_any` | list | e.g. `["factura", "recibo"]` |
| `cascade_status_any` | list | `confirmed` \| `probable` \| `rejected` \| `unknown` |
| `cascade_min_confidence` | float | Minimum cascade confidence |
| `cascade_stage_max` | int | Match only if `cascade.stage_used <= N` (e.g. `1` = no VLM; `2` allows OCR stage) |

### 5.10 Action reference (YAML)

| Field | Description |
|-------|-------------|
| `move_to` | Destination directory template (supports `{cascade_category}`) |
| `rename` | Filename template (supports `{cascade_category}`) |
| `create_target_dir` | Default `true` |
| `on_collision` | `append` \| `skip` \| `replace` |

`{cascade_category}` renders the cascade label as a path-safe slug
(`uncategorized` without cascade evidence or on `unknown`), e.g.
`~/Pictures/{cascade_category}/{year}`.

### 5.11 Cascade rule example

```yaml
  - id: invoices-cascade
    name: Facturas por cascada
    priority: 15
    stop_after_match: true
    when:
      mime_prefixes: [image/]
      cascade_category_any: [factura, recibo]
      cascade_status_any: [confirmed, probable]
      cascade_min_confidence: 0.65
    then:
      move_to: "~/Documents/Invoices/{year}/{month}"
      create_target_dir: true
      on_collision: append
```

### 5.12 MCP server for agents (0.7–0.9)

FileWizard exposes the same pipeline over **MCP** (Model Context Protocol), a
stdio protocol that Claude, Cursor and other agent clients speak natively.

Install the optional extra:

```bash
pip install -e ".[mcp]"
```

**Start the server** (either one):

```bash
filewizard mcp serve
filewizard-mcp
```

**Agent configuration example (Claude Code / Cursor):**

```json
{
  "mcpServers": {
    "filewizard": {
      "command": "filewizard",
      "args": ["mcp", "serve"],
      "env": {}
    }
  }
}
```

or, using the dedicated script:

```json
{
  "mcpServers": {
    "filewizard": {
      "command": "filewizard-mcp"
    }
  }
}
```

**Tools (9):**

| Tool | Purpose | Mutates? |
|------|---------|----------|
| `ping` | Liveness check | No |
| `filewizard_version` | Returns the product version | No |
| `filewizard_list_presets` | List the presets library | No |
| `filewizard_journal_batches` | Journal history grouped by batch | No |
| `filewizard_collect_facts` | Metadata facts for one file | No |
| `filewizard_plan` | Dry-run plan (uses `perception.yaml` / profile, same as CLI) | No |
| `filewizard_execute` | Apply a plan | **Yes — needs `confirm=true`** |
| `filewizard_undo_batch` | Undo a batch (dry-run default) | **Yes — needs `confirm=true`** |
| `filewizard_apply_agent_labels` | Inject agent labels into a dry-run plan | No |

**Safety rules for agents:**

- Mutation tools (`filewizard_execute`, `filewizard_undo_batch`) **never** act
  without `confirm=true`. Anything else (including `"true"` as a string) is
  rejected with a structured `{ok:false, error:…}` response.
- `filewizard_plan` is always a dry run; nothing is moved. It loads the
  perception stack from `state_dir` (heuristics / cascade / optional OCR-VLM),
  so `cascade_*` rules can match without injecting labels.
- The same journal is used as the CLI, so `filewizard undo` or
  `filewizard_undo_batch` can revert agent-executed moves.
- Responses use absolute paths; errors are structured `{ok:false, tool, error}`.
- **Optional sandbox (0.9+):** set `FILEWIZARD_SOURCE_ROOT=/home/user/Downloads`
  (hard jail; cannot be skipped by tool arguments) **or** add `allowed_roots`
  to `~/.local/share/filewizard/mcp.yaml` (not the tool-call `state_dir`).
  Plan/execute sources *and* destinations outside those roots → structured
  error; `confirm=true` does not bypass it. Unset = same power as CLI.
  If `mcp.yaml` exists but is unreadable, MCP mutate tools **fail closed**
  (error), they do not silently disable the jail.
- **`filewizard_collect_facts` is jailed** like plan/execute when roots are
  set; `filewizard_undo_batch` refuses batches touching paths outside roots
  (fail-closed, dry-run included).
- **Pending journal:** `run`/`undo` warn on stderr if the journal holds
  `pending` rows from an interrupted run; the GUI offers to resolve them.

---

## 6. Perception cascade (0.4.x – 0.8.x)

With profile **`recommended`** (or cascade enabled in Ajustes):

| Stage | What | When |
|-------|------|------|
| **0** | Filename / palette heuristics | Always first on images |
| **1** | Zero-shot CLIP/SigLIP | If `[zeroshot]` installed and stage 1 enabled |
| **2** | OCR (GLM-OCR HTTP or Tesseract) | If not already **confirmed** |
| **3** | VLM JSON labels (Qwen) | If still uncertain / rejected |

Results appear in `features.cascade` and map into `features.vision` / `features.ocr` for rules.

**Cache:** identical file content + same config → reused features (no re-OCR/VLM).  
**Journal:** after apply, `operations.perception` stores a compact snapshot (category, stage, OCR preview length, …) for audit.

Weights are **not** shipped in the Python package. Point `base_url` / `model` at your hardware.

---

## 7. Common workflows

### Organize mixed Downloads (PDF, office, media)

1. GUI → **Organizar descargas (docs y media)** (preset `downloads-docs`)  
2. Source: `~/Downloads`  
3. Preview → Apply. Images are left in place (use a cascade intent for those).

```bash
filewizard run --source ~/Downloads --preset downloads-docs --verbose
```

### Organize screenshots from Downloads

1. GUI → **Separar capturas**, **Organizar imágenes (cascada)**, or **cascada + percepción**  
2. Source: `~/Downloads`  
3. Destination: `~/Pictures/Screenshots/{year}/{month}`  
4. Review → Apply  

### Invoice-like images

1. Start GLM-OCR (and optionally Qwen) or use Tesseract  
2. Profile `recommended` or enable OCR  
3. Rules with `ocr_contains_any` **or** `cascade_category_any: [factura]`  
4. Preview → Apply; check **Cola de revisión** for leftovers.  
   Assigning a category writes `review_labels.json`; the **next** preview uses it as cascade evidence (no HTTP).  

### Cascade-aware preset (`images-cascade-ml`)

Example rules that classify by cascade **category**, not only filename
(`rules_cascade_ml.example.yaml`, seeded as builtin preset):

```bash
filewizard perception init --profile recommended   # cascade ON
# start your llama-server endpoints, then:
filewizard run --source ~/Downloads \
  --preset images-cascade-ml \
  --perception-profile recommended --limit 50 --verbose
```

Rules: invoices/recibos confirmados → `~/Documents/Invoices`; escaneos y
formularios → `~/Documents/Scans`; interfaces/código → Screenshots; fotos
**solo si se resolvieron barato** (`cascade_stage_max: 1`, sin OCR/VLM);
todo lo demás → `~/Pictures/Misc` (fallback determinista). Cambiar de modelo
(otro GGUF) = solo `model` / `base_url` en percepción, no las reglas.  

### Prefix all PDFs with a date

1. **Renombrar archivos**  
2. Extensions: `pdf`  
3. Rename: `{date}_{original_name}`  
4. Preview → Apply  

---

## 8. Troubleshooting

| Problem | What to try |
|---------|-------------|
| `UI not installed` | `pip install -e ".[ui]"` |
| OCR rules never match | Install Tesseract + `.[ocr]`, or start GLM-OCR server; enable OCR / cascade stage 2 |
| Vision / cascade stage 3 empty | Start Qwen endpoint; check **Ajustes → Comprobar endpoints** |
| Zero-shot never runs | `pip install -e ".[zeroshot]"`; enable stage 1 in Ajustes |
| Image dimensions ignored | `pip install -e ".[images]"` |
| Preview shows 0 operations | Relax conditions; check source; raise limit; verify preset rules |
| Slow scans | Use cascade (not dual full OCR+VLM); lower `--limit`; rely on cache on re-run |
| Undo says `missing` | File moved outside FileWizard |
| Undo says `state_mismatch` | File edited after move; blocked on purpose |
| Review queue empty | Queue fills on **wizard preview** when cascade marks unknown/low conf |
| Cola (corrupta) on home | `review_queue.json` was unreadable; open the dialog (`.bak` backup) |
| MCP “source outside allowed_roots” with a custom `state_dir` | Jail yaml is always `~/.local/share/filewizard/mcp.yaml` (or the env). Tool `state_dir` does not move the jail file |
| Uninstall leftover files | `pip uninstall filewizard` does **not** delete state. `filewizard reset --yes` (cache/logs/queue) or `filewizard reset --all --yes` (whole `~/.local/share/filewizard/`) |
| OCR/VLM `base_url` not on localhost | Images are POSTed (base64) to that host. Loopback is the default; a remote URL **leaves this machine** |

---

## 9. What FileWizard will *not* do (by design)

- Follow directory symlinks while scanning (avoids cycles)  
- Run without confirmation when applying (GUI confirm / CLI `--execute`)  
- Silently overwrite unexpected files on undo  
- Bundle vision/OCR weights in the core package  
- Require cloud services or accounts  
- Let models move files — only rules + executor do  

---

## 10. Further reading

| Document | Audience |
|----------|----------|
| [README.md](../README.md) | Project overview, install, quick start |
| [AGENTS.md](../AGENTS.md) | Developers & AI agents: architecture and status |
| [PLAN_CASCADE.md](./PLAN_CASCADE.md) | Cascade design detail |
| [ROADMAP.md](./ROADMAP.md) | Next versions (0.10+) |
| [CHANGELOG.md](../CHANGELOG.md) | Release history |
| [RELEASE.md](./RELEASE.md) | release verify / tag checklist |
| `rules.example.yaml` / `rules_sharp.yaml` | Sample rule sets |
| `perception.example.yaml` | Perception config template |

---

## 11. Glossary

| Term | Meaning |
|------|---------|
| **Dry-run** | Plan operations without changing the filesystem |
| **Facts** | Auditable properties of one file (size, MIME, cascade, OCR, …) |
| **Cascade** | Cheap-first perception pipeline (stages 0–3) |
| **Journal** | SQLite log of moves used for undo (+ perception snapshot) |
| **Review queue** | Manual queue for uncertain classifications |
| **Intent** | High-level goal on the home screen |
| **Collision** | Destination path already exists |
| **ConditionCheck** | Structured reason why a rule matched (for CLI/UI) |
| **Preset** | Saved RuleSet in the local library |
