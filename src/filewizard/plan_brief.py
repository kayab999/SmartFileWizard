"""Spanish description of a plan: what will happen, and why."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable

_APPLY = frozenset({"planned", "dry-run", "done", "manual"})
_HOLD = ("needs-review", "stale", "error")
_SKIP = frozenset({"skipped", "noop"})

_COLLISION = {
    "append": "si ya existe un archivo, se le cambia el nombre",
    "skip": "si ya existe un archivo, se omite",
    "replace": "si ya existe un archivo, se sustituye",
}

_HOLD_LABEL = {
    "needs-review": "en revisión",
    "stale": "cambiaron después del plan",
    "error": "con error",
}


def plan_brief(
    operations: Iterable,
    source: Path | str | None = None,
    scanned: int | None = None,
    scan_errors: Iterable[str] | None = None,
) -> str:
    """One readable contract for the review page and the confirm dialog."""
    ops = list(operations)
    if not ops:
        return "No hay nada que aplicar."

    lines: list[str] = []
    if source:
        lines.append(f"Origen: {source}")
    if scanned is not None:
        lines.append(f"Archivos leídos: {scanned}")

    apply = [op for op in ops if op.status in _APPLY]
    if apply:
        lines.append(_volume_line(apply))
    else:
        lines.append("No hay archivos listos para aplicar.")

    dest_lines = _destination_lines(apply)
    if dest_lines:
        lines.append("Destinos:")
        lines.extend(dest_lines)

    lines.extend(_rule_lines(ops))
    lines.extend(_collision_lines(ops))
    lines.extend(_hold_lines(ops))

    errors = list(scan_errors or [])
    if errors:
        lines.append(f"{len(errors)} rutas no se pudieron leer.")
    return "\n".join(lines)


def result_brief(operations: Iterable) -> str:
    """What an apply run did, plus where to undo it."""
    counts = Counter(getattr(op, "status", "") for op in operations)
    lines: list[str] = []
    if counts.get("done"):
        lines.append(f"Hechos: {counts['done']}")
    if counts.get("stale"):
        lines.append(f"El archivo cambió y no se movió: {counts['stale']}")
    if counts.get("error"):
        lines.append(f"Con error: {counts['error']}")
    other = {
        status: count
        for status, count in counts.items()
        if status not in {"done", "stale", "error"} and count
    }
    for status, count in sorted(other.items()):
        lines.append(f"{status}: {count}")
    if not lines:
        lines.append("No hubo cambios.")
    lines.append("Puedes deshacer desde la ventana principal.")
    return "\n".join(lines)


def _volume_line(apply: list) -> str:
    sizes = [getattr(op, "identity_size", None) for op in apply]
    count = f"{len(apply)} archivos"
    if sizes and all(size is not None for size in sizes):
        return f"{count}, {_human_bytes(sum(int(size) for size in sizes))}"
    return count


def _destination_lines(apply: list) -> list[str]:
    groups: Counter[str] = Counter()
    for op in apply:
        dest = getattr(op, "destination", None)
        if dest is None:
            continue
        try:
            folder = str(Path(dest).parent)
        except (TypeError, ValueError):
            folder = str(dest)
        groups[folder] += 1
    if not groups:
        return []
    ordered = sorted(groups.items(), key=lambda item: (-item[1], item[0]))
    shown = ordered[:3]
    lines = [f"  {folder} ({count})" for folder, count in shown]
    rest = len(ordered) - len(shown)
    if rest:
        lines.append(f"  y {rest} carpetas más")
    return lines


def _rule_lines(ops: list) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for op in ops:
        rule_id = str(getattr(op, "rule_id", "") or "")
        if rule_id in seen:
            continue
        seen.add(rule_id)
        name = getattr(op, "rule_name", None) or rule_id or "regla"
        passed = [
            check.detail
            for check in getattr(op, "conditions", []) or []
            if getattr(check, "passed", False) and getattr(check, "detail", "")
        ]
        if passed:
            lines.append(f"Regla {name}: " + "; ".join(passed))
        else:
            lines.append(f"Regla {name}")
    return lines


def _collision_lines(ops: list) -> list[str]:
    policies = []
    for op in ops:
        policy = getattr(op, "on_collision", None) or "append"
        if policy not in policies:
            policies.append(policy)
    if not policies:
        return []
    described = [_COLLISION.get(policy, policy) for policy in policies]
    lines = ["Colisión: " + "; ".join(described)]
    if "replace" in policies:
        lines.append(
            "El archivo que ya está ahí se guarda y el deshacer lo devuelve."
        )
    return lines


def _hold_lines(ops: list) -> list[str]:
    counts = Counter(getattr(op, "status", "") for op in ops)
    lines: list[str] = []
    for status in _HOLD:
        count = counts.get(status, 0)
        if count:
            lines.append(f"{count} {_HOLD_LABEL[status]}")
    skipped = sum(counts.get(status, 0) for status in _SKIP)
    if skipped:
        lines.append(f"{skipped} se omiten")
    return lines


def _human_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            if unit == "B":
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
