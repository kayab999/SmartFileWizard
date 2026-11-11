# Contributing to FileWizard

Thank you for considering a contribution.

## Development setup

```bash
git clone https://github.com/kayab999/SmartFileWizard.git
cd SmartFileWizard
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ui]"
pytest -q
ruff check src/ tests/
```

## Ground rules

- **Dry-run by default.** Never add a code path that mutates files without an
  explicit `--execute`/`confirm=True`.
- **Perception provides evidence; rules decide; the journal undoes.** Vision/OCR
  never moves files.
- **No new runtime dependencies** without an ADR in `docs/adr/`.
- **UI must not contain filesystem logic** — consumers call the engine.
- Core must import without optional extras (ui, mcp, zeroshot, ocr).

## Pull requests

- One concern per PR; keep diffs minimal and consistent with surrounding style.
- Add or update tests for behaviour changes.
- Run `pytest -q` and `ruff check src/ tests/` before submitting.
- Update `CHANGELOG.md` (Unreleased) for user-visible changes.

## Reporting issues

Use the GitHub issue templates. For security, see `SECURITY.md`.
