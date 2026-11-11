# filewizard.api — public API reference (D4)

Stable, versioned entry points for embedding FileWizard.

```python
from filewizard import api
api.API_VERSION  # "1.0"
```

## Versioning contract

- **Semver.** MAJOR: breaking change. MINOR: backwards-compatible addition.
  PATCH: fixes.
- A function marked deprecated keeps working for at least one MINOR release
  and emits `DeprecationWarning` (see `docs/DEPRECATION.md`).
- Stability applies to the functions below, their parameter names, and the
  shape of their return values. Anything outside `filewizard.api` is
  internal and may change at any time.

## Functions

### `plan(source, ruleset, *, state_dir=None, limit=None, extractors=()) -> (list[PlannedOperation], int)`

Scan *source*, evaluate *ruleset*, return planned operations. **Never
mutates the filesystem or journal** (planning uses a private in-memory or
throwaway journal).

### `execute_operations(operations, *, state_dir, batch_id=None, dry_run=False) -> list[PlannedOperation]`

Execute a previously planned list. Default is **dry-run**; real moves
require explicit `dry_run=False`. Every executed move is recorded in the
journal under `state_dir/journal.db`.

### `undo(state_dir, *, limit=100, execute=False) -> list[dict]`

Revert the most recent completed moves. Default is **dry-run**; pass
`execute=True` to actually revert.

### `collect_facts(path, extractors=()) -> FileFacts`

Metadata + perception evidence for one file (read-only).

### `iter_files(source) -> iterator[Path]`

Safe recursive walk: no symlink following, hidden files skipped by default.

### `deprecated(message)` (decorator)

Mark a callable deprecated; emits `DeprecationWarning` with *message*.

## Guarantees

1. **No silent mutation.** Any mutating call requires an explicit
   mutation flag (dry-run is always the default).
2. **Every move is undoable** via the journal (ADR-0005).
3. **No exception escapes** planning that leaves files moved: `plan` never
   moves anything.
