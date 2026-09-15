from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from pathlib import Path

import yaml

from .cancel import CancelToken, CancelledError
from .engine import Engine
from .executor import Executor, PlannedOperation
from .facts import FeatureExtractor, collect_facts
from .models import Rule, RuleSet
from .scanner import iter_files

logger = logging.getLogger(__name__)


class RulesLoadError(Exception):
    """Raised when a rules YAML cannot be loaded or validated."""


def load_ruleset(path: Path) -> RuleSet:
    """Load and validate a RuleSet from a UTF-8 YAML file (R3, R10)."""
    path = path.expanduser()
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        return RuleSet.model_validate(data)
    except Exception as exc:
        raise RulesLoadError(f"Cannot load rules file {path}: {exc}") from exc


def resolve_rules_path(name_or_path: str | Path) -> Path:
    """
    Resolve a rules file path.

    Search order:
      1. Absolute / expanded path if it exists
      2. CWD
      3. Project root next to package
      4. Presets directory
    """
    candidate = Path(name_or_path).expanduser()
    if candidate.is_file():
        return candidate.resolve()

    name = candidate.name if candidate.suffix else str(name_or_path)
    search_roots = [
        Path.cwd(),
        Path(__file__).resolve().parents[2],
        Path(__file__).resolve().parents[1],
        Path("~/.local/share/filewizard/presets").expanduser(),
    ]
    for root in search_roots:
        path = root / name
        if path.is_file():
            return path.resolve()
        path = root / "rules" / name
        if path.is_file():
            return path.resolve()
        path = root / f"{name}.yaml"
        if path.is_file():
            return path.resolve()

    raise RulesLoadError(f"Rules file not found: {name_or_path}")


def default_extractors(
    *,
    ocr: bool = False,
    vision: bool = False,
    profile: str | None = None,
    state_dir: Path | None = None,
    agent_features: Path | dict[str, dict] | None = None,
) -> list[FeatureExtractor]:
    """Standard perception stack (pluggable providers).

    agent_features: a JSON path (see perception/inject.load_agent_features) or
    an already-loaded mapping. The agent extractor is appended AFTER the
    cascade so agent evidence overrides cascade-derived keys (last-wins).
    """
    from .perception.config import load_perception_config
    from .perception.factory import build_extractors
    from .perception.inject import (
        AgentFeaturesExtractor,
        load_agent_features,
        normalize_agent_features,
    )

    config = None
    if profile:
        from .perception.config import config_from_profile

        config = config_from_profile(profile)
    elif state_dir is not None:
        config = load_perception_config(state_dir=state_dir)

    extractors = build_extractors(
        config,
        force_ocr=ocr,
        force_vision=vision,
        state_dir=state_dir,
    )

    if agent_features:
        # I5: normalize both branches so relative/~/ keys resolve vs CWD
        # instead of silently missing at extract() lookup.
        mapping = (
            load_agent_features(agent_features)
            if isinstance(agent_features, (str, Path))
            else normalize_agent_features(dict(agent_features))
        )
        extractors.append(AgentFeaturesExtractor(mapping))

    # WP-0.11.2: human review labels override cascade (and CLI agent inject).
    if state_dir is not None:
        labels_path = Path(state_dir).expanduser() / "review_labels.json"
        if labels_path.is_file():
            try:
                extractors.append(
                    AgentFeaturesExtractor(load_agent_features(labels_path))
                )
            except Exception as exc:
                logger.warning("review_labels.json skipped: %s", exc)

    return extractors


def plan_operations(
    source: Path,
    rules: RuleSet | Iterable[Rule],
    executor: Executor,
    *,
    extractors: Iterable[FeatureExtractor] | None = None,
    limit: int | None = None,
    include_hidden: bool = False,
    only_paths: set[Path] | None = None,
    on_fact_error: Callable[[Path, Exception], None] | None = None,
    on_progress: Callable[[int, int | None], None] | None = None,
    on_facts: Callable[..., None] | None = None,
    cancel: CancelToken | None = None,
) -> tuple[list[PlannedOperation], int]:
    """
    Shared scan → facts → match → plan pipeline used by CLI and UI.

    on_progress(scanned, limit_or_none)
    on_facts(facts): optional hook after collect_facts (review queue, telemetry)
    cancel: cooperative stop between files (CancelledError if triggered)
    """
    if isinstance(rules, RuleSet):
        rule_list = list(rules.rules)
    else:
        rule_list = list(rules)

    engine = Engine(rule_list)
    extractor_list = (
        list(extractors) if extractors is not None else default_extractors()
    )

    source = source.expanduser().resolve()
    operations: list[PlannedOperation] = []
    scanned = 0

    resolved_only: set[Path] | None = None
    if only_paths is not None:
        resolved_only = {Path(p).expanduser().resolve() for p in only_paths}

    for path in iter_files(source, include_hidden=include_hidden):
        if resolved_only is not None and path.resolve() not in resolved_only:
            continue

        if cancel is not None and cancel.is_cancelled():
            raise CancelledError("Plan cancelled by user")

        if limit is not None and scanned >= limit:
            break

        scanned += 1
        if on_progress is not None:
            on_progress(scanned, limit)

        try:
            facts = collect_facts(path, extractors=extractor_list)
        except Exception as exc:
            if on_fact_error is not None:
                on_fact_error(path, exc)
            else:
                logger.warning("collect_facts failed for %s: %s", path, exc)
            continue

        if on_facts is not None:
            on_facts(facts)

        from .perception.snapshot import perception_snapshot

        snap = perception_snapshot(facts.features)

        for match in engine.evaluate(facts):
            op = executor.plan(
                facts=facts,
                rule=match.rule,
                explanations=match.explanations,
                conditions=match.conditions,
            )
            if op is not None:
                op.perception = snap
                operations.append(op)

            if match.rule.stop_after_match:
                break

    return operations, scanned
