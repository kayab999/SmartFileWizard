# FileWizard — Threat model (D5)

**Scope:** the local engine (CLI, GUI, MCP server), the journal, and the
perception chain. FileWizard is a *local-first* desktop tool: it moves and
renames the user's files. The threat model answers what can go wrong and
which control blocks each risk.

## Trust boundaries

| Boundary | Trust in |
|---|---|
| User files | Untrusted input (malicious names, symlinks, huge files) |
| Rule files / presets YAML | Trusted-ish (user-authored), parsed safely |
| Perception providers (HTTP OCR/VLM) | Untrusted output; never trusted to move files |
| MCP agent clients | Untrusted *intent*, confined by `allowed_roots` jail |
| GitHub release artifacts | Signed + SBOM; users verify checksums |

## STRIDE summary

| Threat | Vector | Control |
|---|---|---|
| **S**poofing | Filename pretending to be a screenshot/invoice ("Screenshot_2026-invoice.pdf") | Filename alone never *confirms* a category (C1 parity, 0.8); cascade needs content evidence for `confirmed` |
| **T**ampering | Substituted file between scan and move (TOCTOU) | Identity capture before extractors (F-07); re-check before publish; O_NOFOLLOW per component in `pathsafe.secure_resolve` |
| **T**ampering | Symlink swap at destination during copy | No-replace publication (`os.rename` with `EEXIST` check); symlinked destination components rejected |
| **R**epudiation | "I never asked FileWizard to move that file" | Immutable SQLite journal with per-operation state machine (ADR-0005); `filewizard verify` batch↔disk audit |
| **I**nfo disclosure | Images leaving the host via perception | Non-loopback OCR/VLM URLs blocked unless `allow_remote: true` (I9); CLI warns on remote profiles |
| **I**nfo disclosure | Cache leaking file contents metadata | Cache dir is 0700 (`ensure_private_dir`); entries keyed by content hash, capped 64 MiB |
| **D**enial of service | Catastrophic regex in a rule | Bounded engine (`regexsafe`): optional `regex` extra with per-call timeout; stdlib fallback + SIGALRM (ADR-0006); fail-closed on timeout |
| **D**enial of service | Bigger-than-memory image / oversized HTTP response | `max_image_bytes/pixels`, `max_upload_bytes/max_response_bytes` caps (WP-D1/F-12) |
| **D**enial of service | Journal grows unbounded | Age-based `purge` + hard quota `enforce_quota` (F-16/E2); protected statuses never evicted |
| **E**levation of privilege | MCP agent escapes the state dir | `allowed_roots` jail (`mcp.yaml` / `FILEWIZARD_SOURCE_ROOT`), path canonicalization via `secure_resolve` |

## Explicit non-goals

- **Multi-user hardening:** FileWizard trusts the local user account.
- **Encrypted storage:** the journal/cache live in plaintext under
  `~/.local/share/filewizard` (0700). Users with confidentiality needs
  should use full-disk encryption.
- **Network hardening:** no telemetry, no accounts, no cloud sync.

## Residual risks (documented, accepted)

- Stdlib-regex fallback has no true timeout off the main thread / non-Unix;
  the `_looks_catastrophic` heuristic and the `regex` extra remain the
  primary controls. Install `pip install filewizard[redos]` for the bounded
  engine (CI always runs it).
- In-move symlink swap (B2) is *mitigated* by O_NOFOLLOW per existing
  component, but a race creating a new final component can still be lost
  on kernels without atomic no-replace semantics at the rename level.
- MCP TOCTOU: the jail re-validates paths at call time; a concurrent
  rename between validation and executor publication is covered by the
  executor's own identity re-check, not by the jail.
