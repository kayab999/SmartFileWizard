"""When model evidence is allowed to move a file by itself.

A match may be applied when any of these is true:

- the matched rule does not read OCR, vision, or cascade evidence
- a deterministic rule in the same set would send the file to the same place
- the file carries a human review label (``vision.provider == "review"``)
- the caller set ``allow_model_only`` for this batch
"""

from __future__ import annotations

from .facts import FileFacts
from .models import Rule
from .template import TemplateError, render_filename_template, render_path_template

MODEL_CONDITION_FIELDS = (
    "ocr_contains_any",
    "ocr_contains_all",
    "vision_label_gt",
    "cascade_category_any",
    "cascade_status_any",
    "cascade_min_confidence",
    "cascade_stage_max",
)

MODEL_HOLD_REASON = (
    "Model evidence does not match a deterministic rule. "
    "Review the file or pass --allow-model-only."
)


def _is_set(value: object) -> bool:
    if value is None or value is False:
        return False
    if value == [] or value == {}:
        return False
    return True


def rule_uses_model_evidence(rule: Rule) -> bool:
    data = rule.when.model_dump()
    return any(_is_set(data.get(name)) for name in MODEL_CONDITION_FIELDS)


def human_review_decided(facts: FileFacts) -> bool:
    vision = facts.features.get("vision")
    if isinstance(vision, dict) and vision.get("provider") == "review":
        return True
    cascade = facts.features.get("cascade")
    return isinstance(cascade, dict) and cascade.get("provider") == "review"


def _action_key(rule: Rule, facts: FileFacts) -> tuple[str, str] | None:
    try:
        move = (
            str(render_path_template(rule.then.move_to, facts))
            if rule.then.move_to
            else ""
        )
        rename = (
            render_filename_template(rule.then.rename, facts)
            if rule.then.rename
            else ""
        )
    except TemplateError:
        return None
    return move, rename


def model_match_may_apply(
    rules: list[Rule],
    facts: FileFacts,
    matched: Rule,
    *,
    allow_model_only: bool,
) -> bool:
    """False when this match must wait for a person."""
    if allow_model_only or not rule_uses_model_evidence(matched):
        return True
    if human_review_decided(facts):
        return True
    wanted = _action_key(matched, facts)
    if wanted is None:
        return False
    from .engine import Engine

    deterministic = Engine(
        [rule for rule in rules if not rule_uses_model_evidence(rule)]
    )
    for other in deterministic.evaluate(facts):
        if _action_key(other.rule, facts) == wanted:
            return True
    return False
