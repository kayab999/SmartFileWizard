from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Condition(BaseModel):
    """
    Conditions a file must satisfy to activate a rule.

    If always=true, the rule matches immediately.
    Unknown fields are rejected so a typo cannot silently drop a check.
    """

    model_config = ConfigDict(extra="forbid")

    always: bool = False

    extensions: list[str] | None = None
    mime_prefixes: list[str] | None = None
    filename_regex: str | None = None
    path_contains: list[str] | None = None

    size_gt: int | None = None
    size_lt: int | None = None

    min_width: int | None = None
    min_height: int | None = None
    min_aspect: float | None = None
    max_aspect: float | None = None
    older_than_days: int | None = None

    ocr_contains_any: list[str] | None = None
    ocr_contains_all: list[str] | None = None

    # Example:
    # vision_label_gt:
    #   document: 0.90
    #   screenshot: 0.85
    vision_label_gt: dict[str, float] | None = None

    # V0.3: deterministic sharpening
    filename_pattern_any: list[str] | None = None
    has_exif_date: bool | None = None
    has_camera_metadata: bool | None = None
    exif_software_contains: list[str] | None = None
    min_unique_colors: int | None = None
    max_unique_colors: int | None = None

    # Negations
    not_extensions: list[str] | None = None
    not_filename_regex: str | None = None
    not_filename_pattern_any: list[str] | None = None
    not_path_contains: list[str] | None = None

    # Cascade (perception) conditions
    cascade_category_any: list[str] | None = None
    cascade_status_any: list[str] | None = None
    cascade_min_confidence: float | None = None
    cascade_stage_max: int | None = None

    @field_validator("filename_regex", "not_filename_regex")
    @classmethod
    def validate_regexes(cls, value: str | None) -> str | None:
        """R3: invalid regex fails at rule load time."""
        if value is None:
            return value
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"Invalid regex {value!r}: {exc}") from exc
        return value

    @field_validator(
        "size_gt",
        "size_lt",
        "older_than_days",
        "min_width",
        "min_height",
        "min_unique_colors",
        "max_unique_colors",
        "cascade_stage_max",
    )
    @classmethod
    def _non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("must be >= 0")
        return value

    @field_validator("min_aspect", "max_aspect")
    @classmethod
    def _positive_aspect(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("must be > 0")
        return value

    @field_validator("cascade_min_confidence")
    @classmethod
    def _unit_interval(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("must be between 0 and 1")
        return value

    @field_validator("vision_label_gt")
    @classmethod
    def _vision_scores(
        cls, value: dict[str, float] | None
    ) -> dict[str, float] | None:
        if not value:
            return value
        for label, score in value.items():
            if not 0.0 <= float(score) <= 1.0:
                raise ValueError(
                    f"vision score for {label!r} must be between 0 and 1"
                )
        return value


class Action(BaseModel):
    """
    Action to run when a rule matches.

    move_to may be a template:
      ~/Documents/Invoices/{year}/{month}

    rename may be a template:
      {date}_{original_name}
    """

    model_config = ConfigDict(extra="forbid")

    move_to: str | None = None
    rename: str | None = None

    create_target_dir: bool = True
    # R6: default append; replace never deletes directories (executor enforces).
    on_collision: Literal["skip", "append", "replace"] = "append"

    # Reserved: tags, xattrs, scripts, etc.
    tags: list[str] = Field(default_factory=list)


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    priority: int = 100
    stop_after_match: bool = True

    when: Condition
    then: Action

    @model_validator(mode="after")
    def validate_action(self) -> Rule:
        if not self.then.move_to and not self.then.rename:
            raise ValueError(
                "Rule action must define at least one of: move_to, rename"
            )
        return self


class RuleSet(BaseModel):
    """Rule file. ``name`` and ``description`` are accepted and ignored by the engine."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    name: str | None = None
    description: str | None = None
    rules: list[Rule]
