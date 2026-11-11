# Deprecation policy (D4)

FileWizard follows **semver** for `filewizard.api` (see `docs/API.md`).

## Rules

1. **Announce** a deprecation in this file at release *N*.
2. The deprecated API keeps working in *N* and *N+1*, emitting a
   `DeprecationWarning` (never `PendingDeprecationWarning`).
3. Removal happens at the next MAJOR bump (or after two MINOR releases if
   usage telemetry/feedback indicates nobody depends on it).
4. The warning message always contains the replacement.

## Currently deprecated

*(none — API v1.0 is the first stable surface)*

## How to mark an API deprecated

```python
from filewizard.api import deprecated

@deprecated("Use filewizard.api.plan() instead.")
def old_plan(...): ...
```

## CLI / GUI

- CLI flags follow the same policy: a removed flag triggers a
  `ClickException` with the replacement (no silent behavior change).
- GUI workflows (wizards, dialogs) may be reorganized between MINOR
  releases; user-visible strings are translated via the i18n framework
  and stay available in the release notes.
