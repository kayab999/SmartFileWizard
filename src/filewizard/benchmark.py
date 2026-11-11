"""Simple reproducible benchmark for FileWizard."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def benchmark_directory(
    source: Path,
    *,
    iterations: int = 3,
    limit: int = 100,
) -> dict[str, Any]:
    """Measure plan throughput on a directory (metadata only)."""
    from .facts import collect_facts
    from .scanner import iter_files

    source = Path(source).expanduser().resolve()
    files = list(iter_files(source))[:limit]
    times: list[float] = []
    for _ in range(max(1, iterations)):
        start = time.perf_counter()
        for path in files:
            collect_facts(path)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    avg = sum(times) / len(times) if times else 0.0
    return {
        "files": len(files),
        "iterations": len(times),
        "avg_seconds": avg,
        "files_per_second": (len(files) / avg) if avg > 0 else 0.0,
    }
