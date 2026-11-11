# ADR-0005 — Transactional integrity: operation states, evidence levels and reconciliation

**Status:** Accepted (2026-11-10) · **Scope:** `journal.py`, `executor.py`, `identity.py`, `verify_batch.py`, MCP undo/execute, watcher · **Related:** ADR-0001 (perception/rules/journal), audit findings F-01, F-02, F-03, F-06, F-09, F-17, A-01, A-02.

## Context

The journal records an *intention* (`pending` row) and an *outcome* (`done`/`failed`/…), but a crash between the filesystem mutation and the SQLite update leaves a window where neither the journal nor the filesystem alone tells the truth. Two internal decisions were incompatible:

1. `identity.py` records SHA-256 only for files ≤ 64 MiB (`MAX_CACHE_FILE_BYTES`); larger files get size/mtime/dev/ino only.
2. `Journal.reconcile_pending()` promotes a `pending` row to `done` only via `content_matches()`, which **requires** a hash.

Result: an interrupted large-file move could never be reconciled; and every undo row was created without `content_sha256` at all (A-01), so interrupted undos were never reconcilable either. `replace` displaced the old destination *before* recording the backup path (F-02), `undo` restored backups silently or not at all (F-06), undo causality was inferred from paths (F-17), and MCP inferred `batch_id` from a global "latest batch" query (F-03).

## Model

### 1. Operation states (journal `operations.status`)

Existing states are kept. One state is added; none removed.

| State | Meaning | Set by | Undo-eligible | Purgeable |
|-------|---------|--------|---------------|-----------|
| `pending` | Intention persisted; effect not confirmed | `start_operation` | no | no |
| `done` | Completed **with content-hash evidence** | `finish_operation` / reconcile | yes | no |
| `needs_verify` | Completed per **filesystem-identity evidence only** (no hash recorded); human/tool should verify | reconcile only | yes (guards still apply) | **no** |
| `interrupted` | Owner died and no sufficient evidence to classify | `resolve_pending` | no | yes (retention) |
| `failed` / `skipped` / `error` | Definitive outcomes | `finish_operation` | no | yes |
| `undone` | Original move reversed (A) | `mark_undone` | no | no |
| `undo_partial` | Reverse move (A) succeeded; backup restore (B) pending or failed | `finish_operation` on original | no | no |

`needs_verify` is intentionally *not* `done`: an operation whose evidence is metadata-only must never be presented as content-verified (Invariant 2). It is still undo-eligible because undo re-validates size (and hash when present) on its own before moving.

### 2. Evidence levels

| Level | Check | Sufficient for |
|-------|-------|----------------|
| E1 content | recorded SHA-256 matches destination bytes | `done` |
| E2 fs-identity | recorded source `dev`, `ino`, `size` match destination stat (rename preserves inode on same filesystem) | `needs_verify` |
| E3 presence | destination exists, size matches, nothing else | insufficient → row stays `pending`, later `interrupted` |

Size, path, mtime, `dev` or `ino` alone (E2/E3) never equal content identity (E1). E2 exploits the rename semantics of `shutil.move` on the same filesystem: same (dev, ino, size) at the destination with the source gone is the moved file object. E2 does **not** apply across filesystems (EXDEV copies get a new inode) — those rows fall to E3 and end as `interrupted` unless a hash exists.

Platform limits (declared, not hidden): E2 relies on Linux inode semantics; power-loss durability is **not** claimed — `fsync` of file+directory is best-effort (`fsync_file`, `fsync_dir`), SQLite runs in WAL with `synchronous` default; a power cut can still lose the last committed journal update.

### 3. Invariants (binding)

1. A row may become `done` only with E1 evidence.
2. Ambiguous operations are never presented as complete (`needs_verify` ≠ `done`).
3. Reconciliation is idempotent: promoting, restoring or resolving twice is a no-op, not a duplication.
4. Re-running reconciliation never deletes evidence (backups are only cleared after a successful restore).
5. A backup referenced by a row that is not `done`-with-backup-restored, `undone`, or definitively closed must not be deleted (displaced retention, WP-D4).
6. An undo is complete only when all its effects (reverse move A + displaced restore B) are done; otherwise `undo_partial`.
7. Every undo row records `original_operation_id`; causality is never inferred from paths alone (`verify_batch` falls back to path matching only for legacy rows).
8. A mutation must affect the file whose identity was validated (pre/post extraction identity continuity, WP-B1) — residual windows are documented, not claimed as eliminated.
9. A collision policy must never overwrite a concurrent destination (no-replace move primitive, WP-A5).
10. After any abrupt termination, journal and filesystem must be reconcilable into one of the states above — never silently dropped.

### 4. Protocol changes

- **batch_id** (WP-A4): generated in the request layer, passed into `Executor.execute(batch_id=…)`, returned by MCP verbatim; `null` when the request journaled no rows. `recent_batches` is never used to attribute results.
- **replace saga** (WP-A2): `displaced_path` (deterministic `displaced/{op_id}{suffix}`) is persisted *before* the physical displacement; EXDEV displacement copies to a unique temp, verifies (size ± hash), `fsync`s, renames, and only then removes the original.
- **undo saga** (WP-A3): undo rows record `content_sha256`/`source_mtime_ns`/`source_dev`/`source_ino` of the file being moved back, plus `original_operation_id`; displaced restore failures yield `undo_partial` + explicit report, never a silent `done`.
- **reconciliation ladder** (WP-A1): E1 → `done`; E2 → `needs_verify`; no evidence → `interrupted` (via `resolve_pending`).

### 5. Compatibility

- Schema: additive migration only (`original_operation_id INTEGER` column); existing journals stay valid.
- No new runtime dependency (renameat2 via `ctypes` on Linux; portable fallback `os.link`+`os.unlink` on POSIX; explicit failure otherwise).
- No second source of truth: the journal remains the only operation ledger; `watch_state.json` remains detection-only state.
- Legacy rows without dev/ino/hash reconcile via E3 → `interrupted`, exactly as before; `verify_batch` keeps its path-based fallback for legacy undo rows and reports when it is used.

## Adversarial review notes (R1–R7 round)

### B1 — inode substitution vs in-place modification (R3.2)

The post-move check (`_post_move_status`) compares the landed file's
`dev`/`ino` against the identity captured at plan time. Two distinct
cases must not be conflated:

- **Inode substitution** (file object replaced): different inode ->
  `needs_verify` (detected, never reverted).
- **In-place modification with preserved inode**: same inode, changed
  bytes -> the inode check is **blind** to it. Detection relies on the
  recorded SHA-256 (<=64MiB) or, failing that, on size/mtime. A
  metadata-preserving in-place rewrite (>64MiB, forged mtime) is the
  declared residual window of B1 (still **PARTIAL**).

`needs_verify` is the declared outcome for any detected discontinuity;
it never reverts the move.

### B2 — jail root <-> directory relation during mutation (R3.3-R3.5)

The MCP jail (`mcp_allowed_roots`) resolves the destination at plan
time and re-resolves it at the execute boundary (just before
`Executor.execute`). This closes the plan->execute TOCTOU window but
**not** a substitution *during* the move itself: the executor addresses
the destination by path, and a symlink swap of an intermediate directory
between the re-check and `move_noreplace` could redirect the mutation.

Platform limitation (fail-closed): Linux provides `O_NOFOLLOW` for
directory opens, but applying it to every intermediate component of
every move would change the executor's contract and is out of scope for
this remediation. The guarantee is therefore **fail-closed at the
boundaries we control** (plan + execute re-check) and documented as a
residual for in-move swaps; `filewizard verify` surfaces any resulting
drift. No silent pass is claimed.

### R4 — watcher give-ups and labels/queue coherence

- Give-up events (after `MAX_WATCH_ATTEMPTS` exhaustion) and failed
  enqueues are appended to `watch_giveups.jsonl` (queryable via
  `filewizard watch giveups`), independent of the rotating log.
- `ReviewQueue.resolve()` writes `review_labels.json` **before** the
  queue save (inside the same lock). A crash between the two leaves
  labels ahead of the queue -- by design (labels describe a confirmed
  user resolution); re-resolving converges. No silent loss.
- Every failed enqueue surfaces to the requester: CLI prints
  "NOT enqueued" on stderr; the GUI preview worker exposes
  `enqueue_note` -> non-fatal `QMessageBox.warning` (the error slot is
  reserved for aborting the preview).
- Two real processes enqueue concurrently without loss or duplication
  (`merge_new_items` under flock) -- covered by subprocess tests.

### R5 — retention, ReDoS, permissions

- Retention: a displaced backup of a `done` row is **not** purgeable
  (only `PURGEABLE_STATUSES` are). The retention-ending mechanism is
  the undo: marking the row `undone` makes both the row and its backup
  purgeable after the age cutoff. A `done`+aged backup is therefore
  never purged without an explicit undo first.
- ReDoS: `MAX_RULE_REGEX_LENGTH=512` bounds *size* only. A nested-
  quantifier heuristic (`_looks_catastrophic`) rejects the most common
  catastrophic-backtracking shapes at load time. Residual: the stdlib
  `re` engine has no backtracking limit; a hostile rule file is already
  arbitrary code execution, so the trust boundary is the rule author.
- Permissions: state files are clamped to `0600` on every write (even
  when a preexisting file is `0666`); journal WAL/SHM side files are
  tightened on reopen; rotating logs stay `0600` across rollover and
  reopen. Displaced backups live in a `0700` directory and keep the
  source file's own mode.

### R6 — fsmove backend guarantees (real process termination)

- Backend 1 (renameat2 NOREPLACE): atomic no-replace; EEXIST on any
  existing destination including symlinks (no follow).
- Backend 2 (link+unlink, same fs): a crash between link and unlink
  leaves two hard links (source + destination) sharing one inode; no
  data loss, no overwrite; retry is refused with
  `DestinationExistsError`.
- Backend 3 (cross-fs O_EXCL): reserve -> verified copy (size +- hash,
  fsync) -> rename over our own reservation -> unlink source. A crash
  after the rename leaves source + destination (duplicated, safe); a
  crash mid-copy leaves a 0-byte reservation + staging temp
  (fail-closed: retry refused until manual cleanup).
- Two real processes racing `move_noreplace` to one destination: exactly
  one moves, the loser gets `DestinationExistsError`, no overwrite.
- Symlink source (native path): moved as the link itself; fallback
  path dereferences -- platform limitation, scanner never yields
  symlinks.

## Adversarial review notes

- WP-B1 (F-07) identity continuity: the pipeline captures identity
  **before** extraction and `Executor.plan` refuses to plan when the
  post-extraction capture differs (`stale`). Execute revalidates with
  `identity_matches` and verifies the destination inode after the move
  (same-dev moves); EXDEV copies legitimately change the inode, so the
  journal hash remains the evidence there. **Residual windows, declared
  not eliminated:** (a) between execute-time revalidation and the
  physical move; (b) metadata-preserving substitutions on filesystems
  that can fake mtime — mitigated by the recorded hash (≤64MiB) but not
  for larger files, where dev/ino/size is best-effort evidence;
  (c) in-place content edits keep the same inode — caught by the hash
  when one exists, otherwise by size/mtime only. `needs_verify` is the
  declared outcome for any detected discontinuity.
- `needs_verify` + undo: undo re-checks size/hash itself, so eligibility is safe; `mark_undone` was widened to accept `needs_verify`.
- `needs_verify` rows are not purgeable (they are potential undo evidence).
- Concurrent reconcile + execute: reconcile only touches `pending` rows; `execute` only creates/finishes its own row ids. WAL + `busy_timeout` serializes writes.
- EXDEV replace displacement whose copy fails mid-way: temp file is abandoned in `displaced/` as `{op_id}{suffix}.tmp-*`; purgeable as unreferenced (WP-D4), never adopted silently.

## Tests required per invariant

Each invariant above is backed by a named test in `tests/test_integrity_*` / `tests/test_executor.py` / `tests/test_journal_*.py` / `tests/test_mcp_agent.py`; crash boundaries are exercised by in-process `os._exit` drivers (real process death) where the boundary is between SQLite and filesystem.
