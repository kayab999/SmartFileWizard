# ADR-0004: MCP as pipeline consumer (not a core fork)

- Status: **Accepted** (human OK 2026-08-11 to prioritize 0.7)
- Date: 2026-08-11
- Author: architect (Grok)

## Context

Agents (Claude, Cursor, etc.) integrate tools via MCP. FileWizard already has a stable `pipeline` + journal. Risk: building a parallel “agent filesystem” that bypasses rules/undo.

## Decision

1. MCP lives under `src/filewizard/mcp/` with optional extra `[mcp]`.
2. Every mutating tool maps to existing `plan_operations` / `Executor` / `Journal`.
3. `execute` and destructive undo require explicit `confirm=true`.
4. Agent vision labels use the same feature shape as cascade (`perception/inject.py` from WP-0.5.3).
5. No second rules engine inside MCP.

## Consequences

- MCP tests can unit-test handlers without a full MCP client when possible.
- Versioning: MCP tools document FileWizard version via a version tool.

## Alternatives rejected

- MCP that shells out only to CLI text (fragile parsing).
- Agent moves files via raw `shutil` tools.
