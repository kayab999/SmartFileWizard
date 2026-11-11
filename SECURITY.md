# Security policy — FileWizard

FileWizard is a **local-first** tool. It does not phone home, collect telemetry,
or require accounts. Security reports are welcome.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.11.x  | Yes       |
| < 0.11  | No (upgrade) |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Email: `kayab999@users.noreply.github.com` (GitHub handle) with subject
`[FileWizard security]`. Include:

- affected version (`filewizard --version`)
- steps to reproduce
- impact assessment (data loss, privilege escalation, path traversal, etc.)

You will receive an acknowledgement within 7 days and a fix or mitigation plan
within 30 days when feasible.

## Scope notes

- FileWizard moves files based on **user-authored rules**. A hostile rule file
  is equivalent to arbitrary code execution on the user's files — review rules
  before running them, especially those downloaded from others.
- Perception endpoints (OCR/VLM) are user-configured; sending images to a
  remote endpoint is the user's choice and is warned about in the UI.
- The MCP server requires `allowed_roots` (or `FILEWIZARD_SOURCE_ROOT`) before
  any write; see `docs/AUDIT_REMEDIATION_0.11.1.md` for the jail contract.
- Known residual risks are documented in `docs/AUDIT_REMEDIATION_0.11.1.md`
  (§E) and `docs/adr/ADR-0005-transactional-integrity.md`.
