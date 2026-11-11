# Distribution audit — public release readiness

**Date:** 2026-11-11 · **Version audited:** 0.11.1 · **Tree:** uncommitted working tree
**Scope:** GitHub public distribution (`https://github.com/kayab999/SmartFileWizard`), one-click `.deb`/AppImage.

## A. Required files in the public repository

### Core / packaging (must ship)
- `README.md` — install matrix, version, download links
- `LICENSE` (MIT) — present
- `pyproject.toml` — dynamic version from `src/filewizard/__init__.py`
- `src/filewizard/` — engine + optional UI
- `packaging/appimage/`, `packaging/deb/`, `packaging/filewizard.desktop`, `packaging/install-desktop.sh`
- `.github/workflows/test.yml`, `.github/workflows/release.yml`
- `docs/USER_MANUAL.md`, `docs/RELEASE.md`
- `rules.example.yaml`, `perception.example.yaml`, `rules_downloads.example.yaml`

### Developer / audit (optional but useful)
- `AGENTS.md`, `docs/WORK_PLAN.md`, `docs/IMPLEMENTER_BRIEF.md`, `docs/adr/`
- Tests under `tests/` (CI gate)

### Must NOT ship in the public tree
- `.venv/`, `dist/`, `build/`, `*.db`, `__pycache__/` (already ignored)
- Generated audit bundles (`AUDIT_REMEDIATION_CONSOLIDATED.md`, `/tmp/opencode/audit/`) — keep outside the repo
- Local perception configs with endpoints/keys

## B. Version state

- `src/filewizard/__init__.py` bumped to **0.11.1**.
- `packaging/nfpm.yaml` bumped to **0.11.1**.
- README/USER_MANUAL/AGENTS updated to 0.11.1.
- `CHANGELOG.md` still has `## [Unreleased]`; rename to `## [0.11.1]` before tagging.

## C. Build validation (local)

- PyInstaller one-dir build: **OK** (`dist/FileWizard/`, 9.9 MB entrypoint).
- `.deb` build: **OK** — `dist/filewizard_0.11.1_amd64.deb` (73 MB).
- SHA256: `bc72007fa2d36a04fb0080ace7a96c0b3e4e2620a51689d5ede7c0ef9334381f`
- Smoke: `FileWizard --version` → `filewizard, version 0.11.1`; `--help` lists CLI commands.
- AppImage not built locally (needs `appimagetool`); release workflow builds it on ubuntu-22.04.

## D. Priority-ordered actions

### P0 — before any public tag
1. Rename `## [Unreleased]` → `## [0.11.1] — 2026-11-11` in `CHANGELOG.md` and add the R8 notes.
2. Remove generated audit bundles from the repo root (already moved to `/tmp/opencode/audit/`); keep `docs/AUDIT_REMEDIATION_0.11.1.md` only if desired for transparency.
3. Run `pytest -q` + `ruff check src/ tests/` on a clean checkout (currently 385 passed, ruff clean).
4. Confirm `filewizard --version`, `filewizard-ui` smoke and `filewizard perception status`.
5. Update `docs/RELEASE.md` to 0.11.1 (or create `docs/RELEASE_0.11.1.md`).

### P1 — build & publish artifacts
6. Run `bash packaging/appimage/build.sh` on ubuntu-22.04 → `FileWizard-0.11.1-x86_64.AppImage`.
7. Run `bash packaging/deb/build-deb.sh` → `filewizard_0.11.1_amd64.deb` (done locally; rebuild in CI for reproducibility).
8. Tag `v0.11.1` and push → release workflow uploads both artifacts + release notes.
9. Attach SHA256 checksums to the release.

### P2 — professional polish (post-release)
10. Add `SECURITY.md`, `CONTRIBUTING.md`, issue/PR templates.
11. Add a `pip install filewizard` publishing step (PyPI) if desired.
12. Flatpak manifest (backlog).
13. Automated GUI tests (currently none).

## E. Current blockers
- None for local build. Public release still gated on the PARTIAL verdict items (CI green run + independent diff review) and authorization to tag/push.
- `release.yml` test job allows `pip install -e ".[dev,ui]" || pip install -e ".[dev]"` fallback; tighten to fail hard (already done in `test.yml`).
