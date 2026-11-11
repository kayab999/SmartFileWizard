# Structured JSON output (C4)

All read-style commands accept `--json` for machine consumption. The
schemas below are **stable** (same versioning contract as
`docs/DEPRECATION.md`): fields may be added, never removed or retyped,
without a MINOR bump.

Exit codes and stderr diagnostics are unchanged by `--json`; only stdout
is machine-readable.

| Command | Flag | Shape |
|---|---|---|
| `run` (dry-run) | `--json` | `[{source, destination, rule_id, rule_name, status, error, explanations, conditions, perception}]` |
| `run --execute` | `--json` | same array, post-execution statuses |
| `undo` (dry) | `--json` | `[{id, source, destination}]` |
| `undo --execute` | `--json` | result dicts as returned by undo (`status`, `source`, `destination`, …) |
| `presets list` | `--json` | `[{name, rule_count, description}]` |
| `perception status` | `--json` | full status object (profile, ocr, vision, cascade, cache, endpoints) |
| `doctor` | `--json` | `{version, python, platform, state_dir, checks: [{name, ok, detail}]}` |
| `watch list` | `--json` | `[{name, source, preset, rules, interval_s, dry_run}]` |
| `verify` | `--json` | batch list `{problem, batches: [{batch_id, started_at, done, total}]}` or report `{batch_id, found, problem, done, holds, divergences, awaiting_review, passed}` |
| `benchmark` | *(human only)* | printed table; use `benchmark.py` programmatically for JSON |

## Example

```bash
$ filewizard run --source ~/Downloads --preset downloads-docs --json
[
  {
    "source": "/home/carlos/Downloads/report.pdf",
    "destination": "/home/carlos/Documents/2026/11/report.pdf",
    "rule_id": "downloads-pdf",
    "status": "planned",
    "conditions": [{"key": "extensions", "passed": true, "detail": ".pdf"}]
  }
]
```

## Parsing notes

- Output is a single JSON document (UTF-8) written to stdout; warnings go
  to **stderr** so piping stays clean.
- Statuses use the engine vocabulary: `planned | dry-run | done |
  skipped | noop | needs-review | needs_verify | error`.
