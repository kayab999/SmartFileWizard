from __future__ import annotations

from typing import Any

from ..models import Action, Condition, Rule


def parse_csv(value: str | None) -> list[str] | None:
    if not value:
        return None

    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def csv_from_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)

    return str(value)


def build_rule(options: dict[str, Any]) -> Rule:
    """Build a core Rule from wizard options."""

    if options.get("always"):
        condition = Condition(always=True)
    else:
        size_gt_mb = int(options.get("size_gt_mb", 0) or 0)

        camera = options.get("has_camera_metadata")

        condition = Condition(
            extensions=parse_csv(options.get("extensions")),
            mime_prefixes=["image/"] if options.get("image_only") else None,
            filename_regex=options.get("filename_regex") or None,
            path_contains=parse_csv(options.get("path_contains")),
            size_gt=size_gt_mb * 1024 * 1024 if size_gt_mb > 0 else None,
            ocr_contains_any=parse_csv(options.get("ocr_contains_any")),
            filename_pattern_any=parse_csv(options.get("filename_pattern_any")),
            not_filename_pattern_any=parse_csv(
                options.get("not_filename_pattern_any")
            ),
            has_camera_metadata=bool(camera) if camera is not None else None,
            cascade_category_any=parse_csv(options.get("cascade_category_any")),
            older_than_days=int(options["older_than_days"])
            if options.get("older_than_days")
            else None,
        )

    move_to = (options.get("move_to") or "").strip() or None
    rename = (options.get("rename") or "").strip() or None

    action = Action(
        move_to=move_to,
        rename=rename,
        create_target_dir=bool(options.get("create_target_dir", True)),
        on_collision=options.get("on_collision", "append"),
    )

    return Rule(
        id="ui-rule",
        name=options.get("rule_name", "UI rule"),
        priority=10,
        stop_after_match=True,
        when=condition,
        then=action,
    )
