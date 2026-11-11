# FileWizard — Next phases action plan (P1–P4)

**Date:** 2026-11-11 · **Baseline:** 0.11.1 (commit 4478d13) · **Tests:** 389 passed
**Source plan:** `/home/carlos/.opencode/plan/filewizard-10-10-plan.md`

This document converts the 10/10 plan into executable work packages with
files, tests, dependencies and exit criteria. No code changes are made here.

---

## Phase 0 — remaining closure (P0, ~1 week)

Already done: chunked hashing, symlink jail guard, atomic recovery, property
tests (2), GUI smoke tests (2).

### P0-6 — ReDoS engine (P1 priority)
- **ADR:** create `docs/adr/ADR-0006-regex-engine.md` (optional dep `regex`).
- **Code:** `regexsafe.py` — if `regex` installed, use `regex.compile` + `timeout=`; else stdlib + heuristic + `signal.SIGALRM` guard in engine (Unix only, fail-closed on timeout → `needs_verify`-style refusal).
- **Tests:** catastrophic patterns (`(a+)+b`, `(a|aa)+$`) must not hang beyond 1 s; fuzz 1000 random patterns.
- **Exit:** E4 no longer PARTIAL (or documented as PARTIAL with explicit trust boundary).

### P0-7 — TOCTOU closure (O_NOFOLLOW)
- **Code:** new `src/filewizard/pathsafe.py` with `secure_resolve(path)` walking components via `openat(..., O_NOFOLLOW | O_DIRECTORY)`; use in `_apply_destination_jail`, `mcp_allowed_roots`, executor destination parent check.
- **Tests:** symlink at every depth rejected; property test with random path components.
- **Exit:** B2 residual closed or documented platform limitation.

### P0-8 — GUI surface for `needs_verify`
- **Code:** `ui/main_window.py` — badge/count + filter in journal panel; `ui/verify_dialog.py` (new) listing needs_verify rows with "verify now" action calling `filewizard verify` logic.
- **Tests:** pytest-qt smoke for the dialog.

---

## Phase 1 — Performance & perception maturity (3–4 weeks)

### P1-1 — Batch inference queue for zero-shot
- **Files:** `perception/zeroshot.py`, new `perception/batch_queue.py`.
- **Deliverable:** configurable batch size, GPU/CPU auto-detect, async results; `CascadeExtractor` calls batch API.
- **Tests:** mock batch with 1/8/32 images; verify identical results to single-image path.

### P1-2 — Async perception pipeline
- **Files:** `pipeline.py`, `facts.py`, `ui/workers.py`.
- **Deliverable:** `asyncio`-based extractor scheduling; non-blocking UI progress.
- **Tests:** cancellation mid-batch; no deadlock under 100 files.

### P1-3 — Cache eviction & metrics
- **Files:** `perception/cache.py`.
- **Deliverable:** LRU by size + age; `filewizard cache stats` / `cache purge`.
- **Tests:** eviction under size cap; metrics accuracy.

### P1-4 — Profiling baseline
- **Files:** new `src/filewizard/benchmark.py`, CLI `benchmark` command.
- **Deliverable:** reproducible numbers (files/s, perception latency) in docs.

### P1-5 — Stage-1 prompt i18n
- **Files:** `perception/prompts.py`, `perception/zeroshot.py`.
- **Deliverable:** English/Spanish prompt templates selectable by config.

---

## Phase 2 — Distribution professionalism (2–3 weeks)

### P2-1 — Signed artifacts
- **Files:** `.github/workflows/release.yml`.
- **Deliverable:** GPG/cosign signing; publish `.sig` + checksums.

### P2-2 — SBOM
- **Deliverable:** CycloneDX SBOM generated in CI, attached to release.

### P2-3 — Flatpak
- **Files:** new `packaging/flatpak/`.
- **Deliverable:** manifest + Flathub submission.

### P2-4 — PyPI publishing
- **Deliverable:** trusted publishing workflow; `pip install filewizard`.

### P2-5 — Auto-update channel
- **Deliverable:** AppImage update (zsync) or in-app notice.

### P2-6 — Reproducible builds
- **Deliverable:** pinned build env, reproducible PyInstaller.

---

## Phase 3 — UX, accessibility & i18n (3–4 weeks)

### P3-1 — Accessibility audit
- **Deliverable:** keyboard-only flows, screen-reader labels, contrast, focus management; pytest-qt a11y smoke.

### P3-2 — i18n framework
- **Deliverable:** Qt `.ts`/`.qm`; Spanish + English shipped; `filewizard --lang`.

### P3-3 — Drag-and-drop + preview polish
- **Deliverable:** drop files onto wizard, richer preview, thumbnails.

### P3-4 — `filewizard doctor`
- **Deliverable:** environment diagnostics (Python, deps, permissions, journal, cache).

### P3-5 — Structured JSON output
- **Deliverable:** `--json` for all commands; stable schema documented.

---

## Phase 4 — API stability & ecosystem (2–3 weeks)

### P4-1 — Public API module
- **Files:** new `src/filewizard/api.py`.
- **Deliverable:** documented, versioned surface (`filewizard.api`).

### P4-2 — Deprecation policy
- **Deliverable:** semver, deprecation warnings, migration guides.

### P4-3 — Plugin boundary
- **Deliverable:** formal `FeatureExtractor` registration via entry points.

### P4-4 — Type checking in CI
- **Deliverable:** `mypy`/`pyright` gate; typed public API.

### P4-5 — Coverage gate
- **Deliverable:** `pytest-cov` ≥ 90% on core modules.

---

## Dependencies & ordering

```
P0-6/P0-7/P0-8 ──► Phase 1
Phase 1 ──────────► Phase 2
Phase 2 ──────────► Phase 3
Phase 4 ──────────► can run in parallel with Phase 3 (after Phase 1)
```

## Immediate next steps (if authorized)

1. Create WP entries in `docs/WORK_PLAN.md` for P0-6…P0-8.
2. Write ADR-0006 (regex engine decision).
3. Spike: `regex` optional extra + timeout guard (1 day).
4. Spike: O_NOFOLLOW helper + MCP jail integration (1 day).
5. Spike: pytest-qt needs_verify dialog smoke (1 day).

No code changes are made by this document. Implementation requires the
implementer agent.
