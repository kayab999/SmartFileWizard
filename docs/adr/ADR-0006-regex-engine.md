# ADR-0006 — Regex engine with bounded backtracking

**Status:** Accepted (2026-11-11) · **Scope:** rule evaluation, models validation
**Related:** E4 (ReDoS), R8.8, ADR-0005.

## Context

The standard-library `re` engine has no backtracking limit and no timeout.
User-authored rule patterns can therefore hang the engine on catastrophic
backtracking. FileWizard rules are local-trust, but a pasted or downloaded
pattern must not be able to freeze the application.

## Decision

- Prefer the optional `regex` package (`[redos]` extra) which supports a
  per-call `timeout` and is thread-safe.
- Fall back to the stdlib `re` engine with a best-effort
  `signal.SIGALRM` guard on Unix main thread; on other threads/platforms
  the heuristic (`models._looks_catastrophic`) remains the defense.
- All engine regex evaluation goes through `regexsafe.safe_search`, which
  returns `False` on timeout/error instead of propagating a hang.

## Consequences

- A catastrophic pattern may be rejected (no match) rather than hanging.
- `regex` is optional; without it, behavior degrades to the heuristic +
  signal guard and is documented as residual on unsupported platforms.
- No silent change to valid rule semantics.

## Tests

- `test_regexsafe_timeout.py`: `(a+)+b` and `(a|aa)+$` with long inputs
  must not hang beyond 1s.
- Property-based fuzz over 1000 random patterns.
