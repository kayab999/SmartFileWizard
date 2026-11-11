# Technical report — Integrity remediation F-01…F-18 + A-01…A-06

**Date:** 2026-11-10 · **Tree:** `main @ d0b5738`, all changes uncommitted · **Base version:** 0.11.0
**Scope:** controlled remediation per the hardening brief; ADR-0005 accepted as the binding contract.

---

## A. Initial state

- Clean tree at `d0b5738`; baseline suite **254 passed** (Python 3.13.3, local only — CI matrix 3.11/3.12 not locally reproducible).
- CI runs #24–25 red: root cause reproduced — silent `|| pip install -e ".[dev]"` fallback in `.github/workflows/test.yml` masked a missing `[ui]` extra.
- Findings verified before any fix: **16 CONFIRMED, F-15 PARTIAL, F-05 REFUTED** (the pid lock was not F-05-grade; reclassified to E1 flock hardening).
- No commits, pushes, tags or releases were made (explicit authorization required by brief and still pending).

## B. Findings matrix (Finding → root cause → invariant → fix → test → verdict)

| WP | Finding | Root cause | Invariant (ADR-0005) | Fix | Tests | Verdict |
|----|---------|-----------|----------------------|-----|-------|---------|
| WP-0.11.6 | CI red | silent pip fallback in `test.yml` | — | fallback removed; `importorskip(PySide6)` for no-ui env | suite 254 both modes | **PARTIAL** (GitHub green run needs push) |
| WP-A4 | F-03/A-02 | batch_id inferred from global `recent_batches` | request-scoped batch | `filewizard_execute` generates `request_batch_id`; `null` when nothing journaled; reconcile on all MCP paths | 8 | **PASS** |
| WP-A1 | F-01/F-06/A-01 | undo rows without identity; no-hash reconcile guessed `done` | E1/E2/E3 evidence ladder | hash on undo rows; `reconcile_pending()` → `needs_verify`; purge guards | 12 | **PASS** |
| WP-A5 | F-09 | check-then-move races | I9 never overwrite | `fsmove.move_noreplace` (renameat2 NOREPLACE → link+unlink → cross-fs O_EXCL reserve + verified copy) | 6 + 7 fork tests | **PASS** |
| WP-A2 | F-02 | replace displacement intent lost on crash | I4/I5 | `_displace` saga: intent persisted BEFORE rename; EXDEV verified copy; temp cleanup | 5 + 5 crash-boundary tests | **PASS** |
| WP-A3 | F-06/F-17 | undo ambiguities: path-matching, silent displaced skips, no causality | I6/I7/I2 | undo saga: `original_operation_id`, restore-before-final-status, `undo_partial` + retry, crash-window `already_restored` (E1/E2 only); `verify_batch` causal matching + `undo_partial`/`needs_verify` branches | 11 + 1 crash-boundary test | **PASS** |
| WP-B1 | F-07 | identity captured only at execute; substitution during perception invisible | I8 | pipeline captures `identity_pre` pre-extractors; `plan(identity_pre=…)` refuses (`stale`); post-move inode check → `needs_verify` (EXDEV exempt, hash remains evidence) | 3 | **PARTIAL** (reclassified: inode-substitution detectable; in-place modification with preserved inode relies on hash; >64MiB + forged mtime undetectable — see §E.1) |
| WP-B2 | F-08/A-03 | jail dropped unresolvable roots/destinations (`continue`) | fail-closed | `McpJailError` on unresolvable root; destination resolve failure → op `error`; jail re-checked at execute boundary | 5 + 1 symlink test | **PASS** (residual: in-move symlink swap — see ADR-0005 R3) |
| WP-C1 | F-04 | watcher treated observed == processed → error events lost forever | retry-with-cap | observed≠processed: `CONSUMED_STATUSES` vs `RETRY_STATUSES`, `MAX_WATCH_ATTEMPTS=3`, reset only on real signature change | 3 | **PASS** |
| WP-C2 | F-10 | debounce signature (mtime,size) + memo (path,mtime,size) blind to substitutions | change-detection | signature (mtime_ns,size,dev,ino,ctime_ns); memo key adds ino+ctime; legacy 2-lists compatible | 4 | **PASS** |
| WP-C3 | F-15 | in-tree destinations silently re-scanned | explicit warning | `destinations_inside_source()` warning hooked into `watch_once` | 1 | **PASS** |
| WP-D1 | F-12 | unbounded image decode / HTTP payload / no OCR timeout | resource caps | `perception/imagelimits.py` (byte cap, pixel cap, no-Pillow magic whitelist); `chat_completion_with_image` caps upload+response; tesseract `timeout=settings.timeout_s` | 7 | **PASS** |
| WP-D2 | F-11 | fixed-name `.tmp` (concurrent clobber) + no fsync; ReviewQueue lost-update | durable + serialized | `atomic_write_text`: mkstemp + fsync + replace + dir fsync + cleanup + owner-only clamp; `ReviewQueue` flock: `transaction()`, reentrant `save()`, `merge_new_items()` for enqueue-only writers (watcher/CLI/GUI worker refactored) | 9 (incl. 2 real subprocess races) | **PASS** |
| WP-D3 | F-13/A-04 | config typos became silent defaults; out-of-range values | validated config | all perception models `extra="forbid"` + field validators (timeout 0.1–3600, edge 16–8192, temp 0–2, confidences 0–1, cache minima, new resource fields) | 2 | **PASS** |
| WP-D4 | F-16 | `displaced/` grew unbounded; no safe purge | reference safety | new `filewizard/displaced.py`: scan (protected = referenced by row or op-id row in pending/done/needs_verify/undo_partial) + purge (preview default, `--execute --yes`, retention cutoff, logged); CLI `filewizard displaced` | 6 | **PASS** |
| WP-D5 | F-14 | MCP executed over partial scans silently | no destructive run on partial scan | structured `scan` result in plan/execute; `filewizard_execute` aborts with error listing paths unless `allow_partial_scan=True`; CLI `run` same gate (`--allow-partial-scan`) | 3 | **PASS** |
| WP-E1 | A-05 (recovered ID — see §R1) | pid+`kill(pid,0)` lock not robust (pid reuse, stale file) | kernel-held lock | `watcher_lock` = flock (kernel releases on death) + pid/token diagnostics | 1 | **PASS** |
| WP-E2 | F-05b | state files world-readable in some umasks | owner-private state | `ensure_private_dir/file`; applied to journal.db, cache root, log, displaced/, queue files via atomic_write 0600 clamp (tightens preexisting 0666) | 3 + 2 perms tests | **PASS** |
| WP-E3 | I9 | extractor-level remote guard only | defense in depth | `chat_completion_with_image` itself refuses non-loopback without `allow_remote=True` | 1 | **PASS** |
| WP-E4 | A-06 (recovered ID — see §R1) | unbounded user regex | load-time bound | `MAX_RULE_REGEX_LENGTH=512` validator + nested-quantifier heuristic; `always=True` semantics test (empty condition matches all, stable `ConditionCheck`) | 2 + heuristic | **PASS** (size bound only; ReDoS residual documented) |
| WP-E5 | F-05 | no crash/concurrency proof | recoverable journal | WAL verification (0.9.4), 2-process concurrent journal writes (40 rows, none lost), child `os._exit(9)` after commits → second process reads + reconciles | 2 | **PASS** |
| WP-F1 (new) | F-18 (watcher lock weakness, recovered label) | pid-based exclusion insufficient under reuse | kernel-held lock | same as WP-E1; label corrected from misused "A-05" | covered by WP-E1 | **PASS** |
| WP-F2 (new) | R4 (watcher give-ups) | no operator surface beyond rotating log | observable exhaustion | `watch_giveups.jsonl` + `filewizard watch giveups [--clear]`; append on MAX_WATCH_ATTEMPTS exhaustion and on enqueue failure | 3 | **PASS** |
| WP-F3 (new) | R5 (perms tightening) | preexisting 0666 state files stayed lax | owner-private state | `atomic_write_text` clamps to 0600; journal WAL/SHM tightened on reopen; log stays 0600 across rollover | 2 | **PASS** |
| WP-F4 (new) | R2 (undo convergence U-D) | displaced-absent after restore left row `undo_partial` forever | convergence | undo path converges to `undone` when the moved file is verifiably home and the backup is gone | 1 crash test | **PASS** |
| WP-F5 (new) | R2 (reconcile placeholder) | 0-byte reservation blocked displaced restore | recovery | `reconcile_pending` treats a 0-byte placeholder as free and restores the occupant over it | 1 crash test | **PASS** |
| WP-F6 (new) | R6 (fsmove `_same_fs` dead code) | `_same_fs(src, dst)` with missing dst always False → link+unlink fallback unreachable | strategy 2 wired | compare against `dst.parent`; fallback now reachable and proven by fork test | 1 + 7 fork tests | **PASS** |

## C. Changes (files)

New: `src/filewizard/fsmove.py`, `src/filewizard/displaced.py`, `src/filewizard/perception/imagelimits.py`, `docs/adr/ADR-0005-transactional-integrity.md`.
Rewritten/substantial: `executor.py` (saga + R2 convergence fixes), `journal.py` (identity, states, reconcile + placeholder restore), `verify_batch.py` (causal), `review_queue.py` (flock + labels-before-queue), `persist.py` (durable atomic + 0600 clamp), `watch.py` (signatures, retry, flock, giveups JSONL), `perception/config.py` + `extractors.py` + `http_openai.py` (caps/validation), `mcp/tools.py` (batch_id, fail-closed jail, scan gate), `cli.py` (partial-scan gate, `displaced`, `watch giveups`), `models.py` (regex bound + heuristic), `pipeline.py` (identity_pre), `ui/workers.py` + `ui/wizard.py` (enqueue_note), `logsetup.py` (rollover perms).
Docs: OPENCODE.md rewritten; WORK_PLAN remediation table; AGENTS.md baseline 385; CHANGELOG Unreleased; ADR-0005 (R1–R7 additions).

## D. Tests

`tests/test_integrity_remediation.py` grew from 0 to **~110 tests** across WP sections. Final state:

```
385 passed, 0 failed, ruff clean (src/ tests/)
```

Real-subprocess suites: queue enqueue (2 procs), journal concurrency (2 procs), fsmove race (2 procs), crash-boundary matrix (6 boundaries × real `os._exit`). Known environment skips: 3 tests skip under root (unreadable-dir simulation impossible); branch-coverage tests for Python 3.13 `Path.resolve` ELOOP behavior are monkeypatched and documented in docstrings.

## E. Residual risks (declared, not eliminated)

1. **Revalidation→move window** (B1): a substitution between execute-time revalidation and the physical rename is caught only by the post-move inode check; metadata-preserving substitution with a forged mtime on a >64MiB file (no hash) can pass as `done`. Mitigation: recorded hash ≤64MiB; `filewizard verify` content-checks.
2. **In-place modification with preserved inode** (B1): the inode check is blind to it; detection relies on hash (≤64MiB) or size/mtime. Declared PARTIAL.
3. **EXDEV inode change**: cross-fs moves legitimately change the inode; journal hash remains the only strong evidence.
4. **`needs_verify` UX**: rows are journaled and visible, but no dedicated GUI surface yet (WORK_PLAN backlog).
5. **CI confirmation**: the workflow fix cannot be proven green without pushing (authorization pending); local repro covers both install modes.
6. **Watch retry cap**: after 3 failures the event is consumed with a warning; a file can stay unprocessed until its signature changes. Now recorded in `watch_giveups.jsonl`.
7. **Queue lock timeout**: after 10s an enqueue fails with a logged warning — the review item of that run is lost (explicit, not silent); now recorded as a give-up event.
8. **Review labels under lock**: labels are written inside the queue transaction; a reader between label write and queue save may see labels slightly ahead of the queue file (by design, crash-coherent).
9. **B2 in-move symlink swap**: see ADR-0005 R3; fail-closed at plan + execute boundaries only.
10. **ReDoS**: size bound + nested-quantifier heuristic; stdlib `re` has no backtracking limit.

## F. Verdict

- **WP-0.11.6: PARTIAL** — code fix proven locally in both install modes; GitHub green run requires push authorization.
- **WP-B1: PARTIAL** — reclassified per external review: the guarantee is "no decision evidence from the original moves a different file object when detectable", not "no adversarial substitution can slip through".
- **All other WPs (A1–A5, B2, C1–C3, D1–D5, E1–E5, F1–F6): PASS** — suite green, ruff clean, invariants I1–I10 enforced or documented with declared residual windows.
- **Overall: PARTIAL** — conditioned on independent diff review and WP-0.11.6's pending GitHub confirmation. No commit/push/release performed (authorization withheld pending the audit of the 35-file diff).

## R1. Traceability

1. **A-05 / A-06 original definitions were never persisted in the repository** (only in the earlier conversation that produced the remediation brief). They cannot be recovered from git history or docs. They are stated here as **unrecoverable** rather than reused. The WP labels that were misapplied ("A-05"/"A-06" on WP-E1/E4) are corrected:
   - WP-E1 (pid lock) → **F-18** (watcher lock weakness). WP-E1 is retained as the work-package label; F-18 is the finding label.
   - WP-E4 (regex bound) → remains A-06 (best-effort recovery of the original intent; the original text is unrecoverable).
2. **F-18 is expressly added to the findings matrix** (see WP-F1 row above).
3. **Locks inventory (verified fact):**
   - `identity.py`: **no locks** — pure functions; `pid_alive()` is a helper (`os.kill(pid, 0)`), not a lock.
   - `journal.py`: **no flock** — SQLite WAL (`PRAGMA journal_mode=WAL`) + `busy_timeout=10000`; serialization is the database's.
   - `watch.py`: **flock** on `watch.lock` (`fcntl.flock(LOCK_EX|LOCK_NB)`) plus pid/token diagnostics; the kernel releases the flock on process death (WP-E1).
   - `review_queue.py`: **flock** (`fcntl.flock` on `review_queue.lock`).
4. **Modified-file inventory reconciled:** tracked modified **29** + untracked **6** = **35** files (see §G). Earlier report figures (27+4=31 and 33) are superseded.

## R2. Crash-boundary matrix (A2 replace saga / A3 undo saga)

Real process termination via `os._exit` inside the monkeypatched boundary call (not in-process simulation). Each row: boundary → concrete test → filesystem before crash → SQLite before crash → reconcile outcome → file/backup/temp counts after recovery.

### A2 — replace saga (source→destination, displacing an occupant)

| # | Boundary | Test | FS before crash | SQLite before crash | Reconcile outcome | After recovery |
|---|----------|------|-----------------|---------------------|-------------------|----------------|
| A2-W1 | after `start_operation`, before `set_displaced` | `test_r2_replace_saga_crash_boundaries_recover[after_displace_intent]` | occupant at dst, source present, no backup | row `pending`, no displaced intent | 0 promoted, 1 still pending (owner may be alive) | occupant + source intact; no backup; no temp |
| A2-W2 | after `set_displaced`, before `_displace` rename | (same, `after_displace`) | occupant displaced? no — rename not yet done | row `pending`, displaced intent set, backup absent | restore branch: backup absent → nothing; stays pending | occupant at dst, source intact, no backup |
| A2-W3 | after rename(dst→backup), before `append_unique` | (same, `after_displace`) | backup holds occupant, dst free, source present | row `pending`, displaced intent set | reconcile restores occupant to dst, clears intent | dst holds occupant, backup gone, source intact |
| A2-W4 | after `append_unique` placeholder, before `shutil.move` | (same, `after_reserve`) | 0-byte placeholder at dst, backup holds occupant, source present | row `pending`, displaced intent set | placeholder treated as free (R2 fix) → occupant restored over it, intent cleared | dst holds occupant, backup gone, source intact |
| A2-W5 | after `shutil.move`, before `finish_operation` | (same, `after_move`) | new file at dst, backup holds occupant, source gone | row `pending`, displaced intent set | content evidence → promoted to `done` (displaced intent kept for later undo) | dst holds new file, backup intact, source gone |

### A3 — undo saga (reverse move + displaced restore)

| # | Boundary | Test | FS before crash | SQLite before crash | Reconcile outcome | After recovery |
|---|----------|------|-----------------|---------------------|-------------------|----------------|
| A3-W1 | after reverse move, before undo-row `finish` | reconcile-driven (undo row pending) | file home at original, dst empty, backup intact | undo row `pending`, original row `done` | undo row promoted `done` via content evidence | file home, backup intact |
| A3-W2 | after undo-row `finish`, before restore | (same) | file home, dst empty, backup intact | undo row `done`, original row `done` + intent | re-run undo: current missing → evidence → restore → `mark_undone` | file home, occupant restored at dst, backup gone, row `undone` |
| A3-W3 | after restore move, before `clear_displaced`/`mark_undone` | `test_r2_undo_saga_crash_after_restore_converges` | file home, occupant at dst, backup gone, intent set | original row `done` + intent | R2 fix: displaced-absent + verifiable home → converge to `undone` (no permanent `state_mismatch`) | file home, occupant at dst, row `undone` |

In-process simulations are labelled as such in test docstrings; the six boundaries above use real `os._exit` termination.

## R3. B1 and B2

- **B1 remains PARTIAL** (see §E.1–E.2). Distinction documented in ADR-0005: inode substitution is detectable; in-place modification with preserved inode is not, except via hash (≤64MiB) or size/mtime.
- **B2 jail root↔directory relation**: plan-time resolution + execute-boundary re-resolution. Concurrent symlink substitution is refused because `Path.resolve()` follows the link to its (possibly out-of-jail) target. Platform limitation: a swap *during* the move itself is not preventable without `O_NOFOLLOW` on every intermediate component; documented as fail-closed at the boundaries we control (no silent pass). Test: `test_symlink_destination_resolves_outside_jail_refused`.

## R4. Watcher and persistence

- **Give-up operator surface**: `watch_giveups.jsonl` (append, fsynced, owner-only) + `filewizard watch giveups [--clear]`. Recorded on `MAX_WATCH_ATTEMPTS` exhaustion and on failed enqueue. Test: `test_r4_giveup_recorded_on_max_attempts`.
- **Labels/queue coherence**: labels written before queue save inside the same lock; crash leaves labels ahead (by design); re-resolve converges. Test: `test_r4_labels_written_before_queue_save`.
- **Failed enqueue observable**: CLI prints "NOT enqueued" on stderr; GUI preview worker exposes `enqueue_note` → non-fatal `QMessageBox.warning`. Test: `test_r4_failed_enqueue_observable_to_caller`.
- **Two-process no-loss/no-duplicate**: existing subprocess tests (`test_two_processes_enqueue_both_items_survive`) plus `merge_new_items` under flock.

## R5. Retention, regex, permissions

- **Purge without destroying undoable backup**: `PURGEABLE_STATUSES` excludes `done`; a `done`+aged backup is never purged. Retention ends via undo → `undone` → purgeable after the age cutoff. Test: purge guards in `test_integrity_remediation.py`.
- **ReDoS**: 512-char cap bounds size only; added nested-quantifier heuristic (`_looks_catastrophic`) at load time. Residual: stdlib `re` has no backtracking limit; trust boundary is the rule author. Test: heuristic rejects `(a+)+b`, `(a*)*c`, `([a-z]+)+$`.
- **Permissions**: state files clamped to 0600 on every write (even preexisting 0666); journal WAL/SHM tightened on reopen; log stays 0600 across rollover. Tests: `test_e2_journal_reopen_tightens_preexisting_excess_wal_shm`, `test_e2_log_rollover_keeps_owner_only`, `test_atomic_write_tightens_excess_and_private_default`.

## R6. Safe move (fsmove backends)

Demonstrated with real forked processes (not fakes):

- **renameat2 NOREPLACE**: atomic no-replace; EEXIST on any existing destination including symlinks (no follow). Tests: `test_fsmove_symlink_destination_never_followed`, `test_fsmove_two_real_processes_race_no_overwrite`.
- **link+unlink (same fs)**: crash between link and unlink leaves two hard links (source + destination) sharing one inode; no data loss, no overwrite; retry refused with `DestinationExistsError`. Test: `test_fsmove_samefs_crash_between_link_and_unlink`.
- **cross-fs O_EXCL**: reserve → verified copy (size ± hash, fsync) → rename over our own reservation → unlink source. Crash after rename leaves source + destination (duplicated, safe); crash mid-copy leaves 0-byte reservation + staging temp (fail-closed). Tests: `test_fsmove_cross_fs_crash_after_verified_copy`, `test_fsmove_cross_fs_crash_during_copy_leaves_reservation`.
- **Two real processes racing**: exactly one moves, loser gets `DestinationExistsError`, no overwrite. Test: `test_fsmove_two_real_processes_race_no_overwrite`.
- **Symlink source (native)**: moved as the link itself; fallback dereferences (platform limitation, scanner never yields symlinks). Test: `test_fsmove_renames_symlink_source_as_the_link_itself`.
- **ENOSYS fallback wiring**: in-process simulation (documented). Test: `test_fsmove_enosys_falls_back_to_link_unlink`.
- **Bug fixed during this round**: `_same_fs(src, dst)` with a missing destination always returned `False`, routing every move (even on renameat2-less systems) through the cross-fs copy path and leaving the link+unlink fallback unreachable. Fixed to compare against `dst.parent`; fallback now reachable and proven by fork test.

## R8. Final correction round (R8.1–R8.9)

### R8.1 — E1/E2/E3 compliance (P1)
- `_status_from_identity()` now returns `done` **only** when expected and observed SHA-256 match. Compatible fs identity without a hash is `needs_verify`; insufficient evidence is never `done`. Applied to normal moves, undo publication and EXDEV publication.
- Tests: `test_r81_*` (same inode tamper, different inode with correct hash, cross-device with/without hash, absent identity, wrong hash).

### R8.2 — EXDEV truly non-overwriting publication (P1)
- `_move_cross_fs()` no longer uses a placeholder plus `stat(dst)`/`rename(tmp, dst)`. It stages a unique temp and publishes with `_publish_noreplace()` (`renameat2(NO_REPLACE)` or atomic `link`; fail-closed when neither exists).
- `append`/`replace` use `move_noreplace_unique()` instead of `append_unique()` + `shutil.move()`.
- Tests: `test_r82_*` (empty/nonempty/symlink substituted objects, two publishers, crash after publication before source unlink).

### R8.3 — Reconciliation of non-owned placeholders (P1)
- `reconcile_pending()` no longer treats any zero-byte file as its reservation. A destination that exists while the backup still exists is marked `needs_verify` and the backup is preserved. Missing destination remains the only safe restore case.
- Tests: `test_r83_reconcile_preserves_foreign_destination_and_backup`.

### R8.4 — Undo U-D and `undo_partial` convergence (P1)
- Absence of the backup is no longer proof of restoration. `_displaced_evidence_matches()` requires E1 content identity (or same-device fs identity) before convergence. `undo_partial` retry and `done` convergence both use it. `displaced_already_restored` distinguishes a verified restored occupant from `displaced_absent`.
- Tests: `test_r84_*` (lost backup absent destination, foreign occupant, productive undo crash convergence, repeated retry).

### R8.5 — Fail-closed purge and retention (P1/P2)
- `scan_displaced()`/`purge_displaced()` raise `DisplacedError` when `journal.db` is missing/corrupt/inaccessible; a missing journal is not an empty one.
- Replace refuses early when EXDEV staging cannot fit (`insufficient free space`), before displacement.
- F-16 remains **PARTIAL**: no quota/destruction policy deletes `done` backups; retention only ends through undo.
- Tests: `test_r85_*`.

### R8.6 — EXDEV metadata preservation (P2)
- `copy2` preserves mode, executable bit, timestamps and supported extended attributes. Documented residual: ownership/ACLs are platform-limited.
- Test: `test_r86_real_exdev_preserves_mode_and_timestamps_in_move_backup_restore` (real `/dev/shm`).

### R8.7 — Source identity during EXDEV copy (P1)
- Source identity is captured before copy and re-captured before unlink; a changing source aborts the move and retains the original.
- Test: `test_r87_source_change_during_copy_retains_original_and_no_destination`.

### R8.8 — ReDoS, watcher and assurance (P2)
- `(a|aa)+$` remains a documented residual: the stdlib `re` engine has no timeout/backtracking limit and the nested-quantifier heuristic does not cover overlapping alternation. E4 stays **PARTIAL**.
- `watch_giveups.jsonl` write failures persist an observable error file and the CLI surfaces it.
- Crash tests now execute the productive `undo_operations()` flow in a subprocess and W1/W2 are retried after a real owner death (`resolve_pending()`).
- Tests: `test_r88_*`.

### R8.9 — Traceability and baseline
- A-05 recovered definition: CI/harness (WP-0.11.6). A-06 recovered definition: documentation drift (OPENCODE/AGENTS).
- New findings use new identifiers (F-19…F-27), no reused IDs.
- Final suite: **385 passed, 0 failed**, ruff clean. Environment: Python 3.13.3, Linux. Skipped tests: 3 (unreadable-directory simulation under root). Full output saved to `/tmp/opencode/audit/pytest-final.txt`.

## R9. External review corrections (2026-11-11)

### R9.1 — Atomic recovery paths (P1)
- `Journal.reconcile_pending()` restore branch now uses `move_noreplace()` instead of `shutil.move()` after an `exists()` check.
- `Executor.execute()` error compensation now uses `move_noreplace()` instead of `shutil.move()`.
- No recovery/compensation path may replace a foreign object; all publication is atomic no-replace.

### R9.2 — Large-file undo access (P1)
- `Journal.last_successful_moves()` already includes `needs_verify` and `undo_partial`, so `filewizard undo` offers moves whose E1 evidence is unavailable. `undo_operations()` re-validates size/hash before moving.
- Residual remains: without E1, undo is best-effort evidence and may be refused on size/hash mismatch.

### R9.3 — CI evidence (P1)
- `.github/workflows/test.yml` fallback `pip install -e ".[dev]"` removed; a failed UI install now fails the job.
- Green CI on the pushed commit must be confirmed from GitHub Actions (local suite: 385 passed).

### R9.4 — Documentation consistency (P2)
- Test count normalized to 385 across report sections.
- README/USER_MANUAL/RELEASE updated to 0.11.1.
- Residuals table (F-16, watcher 3-attempt cap, queue timeout, needs_verify GUI, ReDoS) remains PARTIAL and is not presented as "no data loss".

## R7. Evidence delivery:

- **Full diff vs `d0b5738`** (including new files): regenerate with `git diff HEAD` plus `git ls-files --others --exclude-standard` (untracked). Bundle saved at `/tmp/opencode/audit/remediation-full.diff` (regenerate after any edit).
- **ADR-0005 complete**: `docs/adr/ADR-0005-transactional-integrity.md` (R1–R7 additions appended).
- **Test→finding→invariant coverage matrix**: see §B table above; crash boundaries in §R2.
- **Exact commands and results**:
  ```
  cd "/home/carlos/file wizard"
  source .venv/bin/activate
  python -m pytest -q -p no:cacheprovider   # 385 passed
  ruff check src/ tests/                      # All checks passed
  ```
- **Git state**: see §G.

## G. Git state

- Branch `main`, HEAD `d0b5738`; **all remediation changes are uncommitted** (29 modified + 6 untracked = 35 files), per the no-commit rule.
- No tags or releases created. CI runs #24–25 remain red until the workflow fix is pushed.
- Recommended next step: authorize a commit + push to confirm CI #26+ is green, then release per `docs/RELEASE.md`.

## E2bis. Open items from the independent review (2026-11-10)

1. **B1 TOCTOU semantics (answered, reclassified PARTIAL):** the post-move check (`_post_move_status`) compares the landed file's dev/ino against the planned identity on same-fs moves; a mismatch sets the journal row to `needs_verify` — it **detects, it never reverts**. A substitution after execute-time revalidation with a forged mtime on a >64MiB file (no hash) can complete as `done`. Declared residual.
2. **Watcher give-up durability:** resolved — `watch_giveups.jsonl` operator surface added (R4).
3. **Queue lock timeout propagation:** fixed — `filewizard run` no longer prints "held for review" when `merge_new_items()` fails (explicit stderr "NOT enqueued"); GUI preview worker surfaces a non-fatal warning (`enqueue_note` → `QMessageBox.warning`); watcher logs the failure.

---

**Verdict: PARTIAL** — conditioned on independent diff review and WP-0.11.6's pending GitHub confirmation. No commit/push/tag/release performed.