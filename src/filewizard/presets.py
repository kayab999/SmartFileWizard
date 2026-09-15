from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from .models import RuleSet
from .pipeline import RulesLoadError, load_ruleset, resolve_rules_path


class PresetError(Exception):
    """Raised when a preset cannot be listed, loaded, or saved."""


def default_state_dir() -> Path:
    return Path("~/.local/share/filewizard").expanduser()


def presets_dir(state_dir: Path | None = None) -> Path:
    root = (state_dir or default_state_dir()).expanduser()
    path = root / "presets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify(name: str) -> str:
    text = name.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text or "preset"


@dataclass(frozen=True)
class PresetInfo:
    name: str
    path: Path
    rule_count: int
    description: str = ""


def _preset_path(name: str, state_dir: Path | None = None) -> Path:
    slug = slugify(name)
    return presets_dir(state_dir) / f"{slug}.yaml"


def list_presets(state_dir: Path | None = None) -> list[PresetInfo]:
    """List user presets in the state directory."""
    root = presets_dir(state_dir)
    items: list[PresetInfo] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            ruleset = load_ruleset(path)
            desc = ""
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                desc = str(raw.get("description") or raw.get("name") or "")
            items.append(
                PresetInfo(
                    name=path.stem,
                    path=path,
                    rule_count=len(ruleset.rules),
                    description=desc,
                )
            )
        except RulesLoadError:
            items.append(
                PresetInfo(
                    name=path.stem,
                    path=path,
                    rule_count=0,
                    description="(invalid)",
                )
            )
    return items


def load_preset(name: str, state_dir: Path | None = None) -> RuleSet:
    path = _preset_path(name, state_dir)
    if not path.is_file():
        # Allow bare stem match
        candidates = list(presets_dir(state_dir).glob(f"{slugify(name)}*.yaml"))
        if len(candidates) == 1:
            path = candidates[0]
        else:
            raise PresetError(
                f"Preset not found: {name!r} (looked in {presets_dir(state_dir)})"
            )
    return load_ruleset(path)


def save_preset(
    name: str,
    ruleset: RuleSet,
    state_dir: Path | None = None,
    *,
    description: str = "",
    overwrite: bool = False,
) -> Path:
    path = _preset_path(name, state_dir)
    if path.exists() and not overwrite:
        raise PresetError(
            f"Preset already exists: {path.name}. Use overwrite=True to replace."
        )

    payload = ruleset.model_dump(mode="python", exclude_none=True)
    if description:
        payload = {"description": description, **payload}

    # I3: atomic write — a crash mid-save must not truncate the library.
    from .persist import atomic_write_text

    atomic_write_text(
        path,
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
    )
    return path


def delete_preset(name: str, state_dir: Path | None = None) -> Path:
    path = _preset_path(name, state_dir)
    if not path.is_file():
        raise PresetError(f"Preset not found: {name!r}")
    path.unlink()
    return path


def import_rules_file(
    source: Path | str,
    name: str | None = None,
    state_dir: Path | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Copy a YAML RuleSet into the presets library."""
    src = resolve_rules_path(source)
    ruleset = load_ruleset(src)
    preset_name = name or src.stem
    return save_preset(
        preset_name,
        ruleset,
        state_dir,
        description=f"Imported from {src.name}",
        overwrite=overwrite,
    )


def ensure_builtin_presets(state_dir: Path | None = None) -> list[Path]:
    """
    Seed the library with bundled rule files if missing.

    Does not overwrite user edits.
    """
    created: list[Path] = []
    builtins = [
        ("images-cascade", "rules_sharp.yaml"),
        ("images-cascade-ml", "rules_cascade_ml.example.yaml"),
        ("downloads-docs", "rules_downloads.example.yaml"),
        ("example", "rules.example.yaml"),
    ]
    for preset_name, rules_name in builtins:
        dest = _preset_path(preset_name, state_dir)
        if dest.exists():
            continue
        try:
            src = resolve_rules_path(rules_name)
        except RulesLoadError:
            continue
        shutil.copy2(src, dest)
        created.append(dest)
    return created
