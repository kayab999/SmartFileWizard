# FileWizard — R9.1 Targeted Remediation

**Date:** 2026-11-12
**Base SHA:** `a29b3f120a205db14d8856a706ba378c614b476a` (unchanged; all changes uncommitted)
**Scope:** targeted fixes for the adversarial review findings of R9. No new features.

## Units implemented

### Unit 1 — Release workflow (artifact handoff + cosign integrity)

`.github/workflows/release.yml` rewritten:
- Top-level `permissions: contents: read`.
- `appimage` and `deb` jobs each `upload-artifact` their outputs (`appimage-dist`, `deb-dist`) with `if-no-files-found: error`.
- New `publish` job (`needs: [appimage, deb]`) downloads both into `dist/` (`merge-multiple: true`), verifies the final artifact set (AppImage + deb + sbom present), generates `SHA256SUMS` over the real final artifacts, verifies with `sha256sum -c`, uploads to release (tag-guarded).
- Cosign: pinned `v2.4.1`, downloads `cosign_checksums.txt`, verifies the binary with `grep ... | sha256sum -c -`. Removed `pip install cosign`.
- SBOM mandatory (`test -s dist/sbom.json`), no `|| true` on checksums.
- GPG signing stays in appimage job (optional, guarded by env).

### Unit 2 — Watcher retry

`src/filewizard/watch.py::retry_watch_paths()`:
- Removed dead conditional `resolved = ... if False else key`.
- Runs under `watcher_lock` (reuses existing coordination; no new lock).
- Counter reset to 1 (re-enqueue condition `0 < attempts < MAX`).

`src/filewizard/cli.py`: `watch giveups` now states attempts unchanged; new `watch retry PATH...`.

Tests added in `tests/test_watch.py` (9): existing registered, nonexistent, unregistered, multiple+duplicates, persistence, malformed giveups, does-not-touch-others, concurrency lock. All pass.

### Unit 3 — Version consistency

`tests/test_version_consistency.py` expanded: CHANGELOG, AppImage README, artifact-name derivation from central version, `__init__.py` + CLI, real dynamic pyproject check (`dynamic = ["version"]` + attr). Removed duplicate `is_file()`.

### Unit 4 — ReDoS in GUI

`src/filewizard/ui/wizard.py`: validation now uses `filewizard.regexsafe.compile_pattern` instead of `re.compile`, so the same engine/timeout policy applies. Removed unused `re` import.

### Unit 5 — Validation

Commands and results (exact):

```
$ ruff check src/ tests/          → All checks passed!
$ mypy src/filewizard --ignore-missing-imports → Success: no issues found in 68 source files
$ QT_QPA_PLATFORM=offscreen pytest -q -p no:cacheprovider
  → 462 passed, 3 warnings; coverage 78.89% (gate 70%)
$ bash -n packaging/appimage/build.sh  → (exit 0)
$ python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('YAML OK')"
  → YAML OK
```

Build real de AppImage/.deb: **no ejecutado** (no hay PyInstaller/appimagetool/nfpm/regex en este entorno). Pendiente de dispatch de CI sobre un commit.

## R9.1.2 — Final review adjustments

### Permissions (release.yml)
- `appimage`: `contents: read`, `id-token: write`.
- `deb`: `contents: read`, `id-token: write`.
- `publish`: `contents: write` only (no id-token).
- Top-level: `contents: read`.

### Watcher lock contract
- `watch_loop` holds `watcher_lock` for its entire lifetime (per-tick state writes occur under it).
- `retry_watch_paths` acquires the same lock; if held, raises `WatcherLockError`.
- `watch_retry` CLI catches `WatcherLockError` and prints an actionable message (stop the watcher, then retry) instead of a traceback.
- Contract documented: `filewizard watch retry` requires the watcher to be stopped. Test `test_retry_watch_paths_while_watcher_active` reproduces the real scenario (watch_loop running in a thread) and asserts rejection.

### Cosign
- Version pinned to `v2.6.5` (maintained 2.x).
- Downloaded as `cosign-linux-amd64`, verified against `cosign_checksums.txt` via `grep ' cosign-linux-amd64$' | sha256sum -c -`, then renamed to `cosign`.
- Residual: cryptographic authenticity (Sigstore TUF/key) not verified; only checksum integrity. Documented as OPEN.

### ReDoS GUI
- `wizard.py` uses `regexsafe.compile_pattern` for validation only; no search at preview time. Effective bounded execution remains in `engine.py` via `safe_search`. Stdlib fallback limitation documented.

### Version tests
- `test_version_consistency.py` checks dynamic pyproject declaration, `__init__`, CHANGELOG, AppImage README, artifact-name derivation. Dynamic resolution by the build backend is not testable without a build (documented).

## Validation (R9.1.2)
```
$ ruff check src/ tests/          → All checks passed!
$ mypy src/filewizard --ignore-missing-imports → Success: no issues found in 68 source files
$ QT_QPA_PLATFORM=offscreen pytest -q -p no:cacheprovider
  → 463 passed, 3 warnings; coverage 78.80% (gate 70%)
```

Residuals unchanged: PID reuse (OPEN), displaced byte capacity (OPEN), TOCTOU B2 (PARTIAL), appimagetool pinning (OPEN), stdlib regex fallback (documented), regex inclusion in packages (pending build).

- PID reuse / owner identity: OPEN (requiere ADR + migración).
- Displaced byte capacity: OPEN.
- TOCTOU B2: PARTIAL (documentado).
- appimagetool sin pinning: OPEN.
- Fallback stdlib `re` sin timeout efectivo fuera del hilo principal: DOCUMENTADO (base source install).
- Inclusión efectiva de `regex` en AppImage/.deb: pendiente de build real.

## Inventario de archivos modificados (R9 + R9.1)

`.github/workflows/release.yml`, `packaging/appimage/README.md`, `packaging/appimage/build.sh`, `packaging/appimage/FileWizard.spec`, `src/filewizard/cli.py`, `src/filewizard/journal.py`, `src/filewizard/watch.py`, `src/filewizard/ui/wizard.py`, `tests/test_r8_assurance.py`, `tests/test_regexsafe_timeout.py`, `tests/test_version_consistency.py`, `tests/test_watch.py`, `docs/AUDIT_REMEDIATION_R9.md`, `docs/AUDIT_REMEDIATION_R9_1.md`.

Sin commit, sin push, sin tag, sin release.
