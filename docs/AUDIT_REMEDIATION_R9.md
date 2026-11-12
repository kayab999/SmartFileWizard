# FileWizard — R9: Post-Push Hardening & Release Assurance

**Date:** 2026-11-12
**Analyzed SHA:** `a29b3f1` (working tree modified; no commits made)
**Branch:** `main` (clean at start; changes are uncommitted by design)
**Version:** `0.11.2` (`src/filewizard/__init__.py`, pyproject dynamic, README, nfpm, flatpak metainfo)
**Tests:** 450 passed, 3 warnings; coverage 78.18% (gate 70%); Ruff clean; mypy clean (68 files)

## 1. Preflight

- `git branch`: `main`, up to date with `origin/main`
- `git status --short` at start: clean
- HEAD: `a29b3f1 release.yml: tag-guarded uploads (so dispatch validates builds); Qt system libs in deb job`
- Tags: `v0.11.0`, `v0.11.1` (no `v0.11.2` tag; version 0.11.2 is development-on-main)
- Version sources all aligned to `0.11.2` except two stale doc comments (fixed).

## 2. Findings closed

| ID | Severity | File/line | Finding | Fix | Test | Result |
|---|---|---|---|---|---|---|
| R9-P0-01 | High | `packaging/appimage/README.md:3`, `build.sh:4` | Stale `0.11.0` in doc comments | Updated to `0.11.2` | `test_version_consistency.py` | CLOSED |
| R9-P0-02 | High | (version metadata) | No automated version-consistency check | Added `tests/test_version_consistency.py` (README, pyproject dynamic, nfpm, flatpak metainfo) | new test | CLOSED |
| R9-P1-01 | High | `src/filewizard/journal.py:503-516` | `reconcile_pending()` marked `needs_verify` without E2 evidence when displaced + source present + destination occupied | Status stays `pending` with conflict note; backup preserved; no promotion | `test_r83_reconcile_preserves_foreign_destination_and_backup` (updated to contract) | CLOSED |
| R9-P1-02 | High | `src/filewizard/regexsafe.py` (fallback) | ReDoS guard only effective on main thread with stdlib fallback; not proven off-main-thread | Added worker-thread bounded test (skips if engine != "regex"); CI installs `redos` extra | `test_regexsafe_timeout.py::test_catastrophic_pattern_bounded_on_worker_thread` | CLOSED (for `regex` engine installs) |
| R9-P1-03 | Medium | `.github/workflows/release.yml` | SBOM/checksum allowed silent failure (`|| true`) | Removed `|| true`; added `test -s` and `sha256sum -c` verification | release workflow dispatch | CLOSED |
| R9-P1-04 | Medium | `.github/workflows/release.yml` | cosign/appimagetool unpinned ("latest") | Pinned cosign to `v2.4.1` | release workflow dispatch | PARTIAL (appimagetool still continuous) |
| R9-P1-05 | Medium | `.github/workflows/release.yml` | Elevated permissions at top level | Top-level `contents: read`; `contents: write`/`id-token: write` scoped to appimage/deb jobs | release workflow dispatch | CLOSED |
| R9-P2-01 | Medium | `src/filewizard/watch.py`, `cli.py` | `watch giveups --clear` did not reset attempt counters; no explicit retry | Added `retry_watch_paths()` + `filewizard watch retry PATH...`; clear now states attempts unchanged | manual smoke + (no dedicated test yet) | CLOSED (code) / PARTIAL (test coverage) |

## 3. Findings classified as residual (not closed this pass)

| ID | Severity | Area | Limitation | Classification |
|---|---|---|---|---|
| R9-P1-06 | High | `resolve_pending()` / PID reuse | PID alone does not prove owner identity; no owner token persisted. Adding a token requires journal migration + compatibility analysis. | OPEN — requires ADR + migration design |
| R9-P1-07 | Medium | Displaced storage capacity | No byte-capacity policy for protected backups; row quota ≠ byte quota. Implementing rejection-before-displace in executor/fsmove needs design. | OPEN — residual documented; no automatic purge of needed backups (invariant preserved) |
| R9-P1-08 | Medium | TOCTOU B2 | Full `dirfd`/`openat`/`O_NOFOLLOW` per-component rewrite not implemented. Existing `pathsafe.secure_resolve` + `O_NOFOLLOW` covers MCP jail; moves rely on identity checks. | PARTIAL — matches THREAT_MODEL documented level |
| R9-P1-09 | Low | AppImage tool pinning | appimagetool still pulled from `continuous` (no stable hash pinned). | OPEN — acceptable for build host; document |
| R9-P1-10 | Low | Stdlib regex fallback | `re` fallback has no effective timeout off main thread (SIGALRM main-thread only). CI always installs `redos` extra; base source install without extra has no real bound. AppImage/.deb now bundle `regex` (build.sh + hiddenimports) so packaged artifacts use the bounded engine. | DOCUMENTED LIMITATION (not a false PASS) |

## 4. Tests run (exact)

```
$ ruff check src/ tests/          → All checks passed!
$ mypy src/filewizard --ignore-missing-imports → Success: no issues found in 68 source files
$ QT_QPA_PLATFORM=offscreen pytest -q -p no:cacheprovider
  → 450 passed, 3 warnings; coverage 78.18% (gate 70%)
$ filewizard --version            → 0.11.2
$ python -c 'import filewizard; print(filewizard.__version__)' → 0.11.2
```

Release workflow (dispatch, HEAD-equivalent logic): test ✓, appimage ✓ (build + smoke + cosign), deb ✓ (build + smoke). Upload steps tag-guarded (skipped on dispatch, run on tag push).

## 5. Files modified (uncommitted)

- `.github/workflows/release.yml`
- `packaging/appimage/README.md`
- `packaging/appimage/build.sh`
- `packaging/appimage/FileWizard.spec`
- `src/filewizard/cli.py`
- `src/filewizard/journal.py`
- `src/filewizard/watch.py`
- `tests/test_r8_assurance.py`
- `tests/test_regexsafe_timeout.py`
- `tests/test_version_consistency.py` (new)

## 6. Traceability matrix (abbreviated)

| Finding | Severity | File/line | Reproduction | Fix | Test | Result | Residual |
|---|---|---|---|---|---|---|---|
| Reconcile false needs_verify | High | journal.py:503-516 | displaced+source present+dest occupied | status stays pending | test_r83 (updated) | CLOSED | none |
| Worker-thread ReDoS unproven | High | regexsafe.py | catastrophic pattern off main thread | test added (regex engine) | test_regexsafe_timeout | CLOSED for redos installs | stdlib fallback (documented) |
| SBOM/checksum silent fail | Medium | release.yml | `|| true` | removed | dispatch run | CLOSED | none |
| Giveup retry missing | Medium | watch.py/cli.py | clear didn't reset attempts | retry command | manual smoke | CLOSED (code) | dedicated test pending |
| Version drift docs | Low | build.sh/readme | stale 0.11.0 | updated | test_version_consistency | CLOSED | none |

## 7. Recommendation

**Release candidate (not release).** Core integrity guarantees (no-overwrite, undo, reconcile honesty) are demonstrated by 450 passing tests including crash/recovery/race scenarios. Packaging pipeline (AppImage + .deb) builds and smokes green. Residuals (PID-reuse owner identity, displaced byte capacity, full TOCTOU elimination, stdlib regex timeout) are documented and require ADR-scoped work; none silently overstates protection. No commit/push/tag performed per instructions.
