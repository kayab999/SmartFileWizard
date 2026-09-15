from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .facts import FileFacts
from .models import Rule


@dataclass(frozen=True)
class ConditionCheck:
    """
    One evaluated condition, structured for CLI/GUI consumers.

    The GUI can render:
      ✓ Es una imagen
      ✓ Mide más de 5 MB
    without reconstructing rule logic.
    """

    key: str
    passed: bool
    detail: str


@dataclass
class Match:
    """A rule that matched a file, with structured evidence."""

    rule: Rule
    conditions: list[ConditionCheck] = field(default_factory=list)

    @property
    def explanations(self) -> list[str]:
        """Human-readable lines for successful checks (CLI / logs)."""
        return [c.detail for c in self.conditions if c.passed]


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _fold(text: str) -> str:
    return _nfc(text).casefold()


class Engine:
    """
    Rule engine.

    Perception extractors do not move files.
    They only produce evidence. The rule engine decides.
    """

    def __init__(self, rules: list[Rule]):
        self.rules = sorted(rules, key=lambda rule: rule.priority)

    def evaluate(self, facts: FileFacts):
        """Yield matches for rules that fully pass (short-circuit on failure)."""
        for rule in self.rules:
            conditions = self._match_conditions(rule, facts)
            if conditions is not None:
                yield Match(rule=rule, conditions=conditions)

    def inspect(self, rule: Rule, facts: FileFacts) -> list[ConditionCheck]:
        """
        Evaluate every defined condition without short-circuit.

        Useful for the GUI to show which checks passed or failed.
        """
        return self._inspect_conditions(rule, facts)

    def _match_conditions(
        self,
        rule: Rule,
        facts: FileFacts,
    ) -> list[ConditionCheck] | None:
        """Return condition list if rule matches, else None."""
        c = rule.when
        checks: list[ConditionCheck] = []

        if c.always:
            checks.append(
                ConditionCheck(key="always", passed=True, detail="always=true")
            )
            return checks

        if not self._has_any_condition(c):
            return None

        for step in self._iter_condition_steps(c, facts):
            checks.append(step)
            if not step.passed:
                return None

        return checks

    def _inspect_conditions(
        self,
        rule: Rule,
        facts: FileFacts,
    ) -> list[ConditionCheck]:
        """All defined conditions, including failures (no short-circuit)."""
        c = rule.when

        if c.always:
            return [
                ConditionCheck(key="always", passed=True, detail="always=true")
            ]

        if not self._has_any_condition(c):
            return [
                ConditionCheck(
                    key="empty",
                    passed=False,
                    detail="rule has no conditions",
                )
            ]

        return list(self._iter_condition_steps(c, facts))

    def _iter_condition_steps(self, c, facts: FileFacts):
        for builder in (
            self._check_extensions,
            self._check_mime,
            self._check_filename_regex,
            self._check_path_contains,
            self._check_size_gt,
            self._check_size_lt,
            self._check_min_width,
            self._check_min_height,
            self._check_min_aspect,
            self._check_max_aspect,
            self._check_older_than_days,
            self._check_filename_pattern_any,
            self._check_has_exif_date,
            self._check_has_camera_metadata,
            self._check_exif_software,
            self._check_max_unique_colors,
            self._check_min_unique_colors,
            self._check_not_extensions,
            self._check_not_filename_regex,
            self._check_not_filename_pattern_any,
            self._check_not_path_contains,
        ):
            step = builder(c, facts)
            if step is not None:
                yield step

        ocr_checks = self._check_ocr(c, facts)
        if ocr_checks is not None:
            yield from ocr_checks

        vision_checks = self._check_vision(c, facts)
        if vision_checks is not None:
            yield from vision_checks

        cascade_checks = self._check_cascade(c, facts)
        if cascade_checks is not None:
            yield from cascade_checks

    @staticmethod
    def _has_any_condition(c) -> bool:
        return any(
            [
                c.extensions is not None,
                c.mime_prefixes is not None,
                c.filename_regex is not None,
                c.path_contains is not None,
                c.size_gt is not None,
                c.size_lt is not None,
                c.min_width is not None,
                c.min_height is not None,
                c.min_aspect is not None,
                c.max_aspect is not None,
                c.older_than_days is not None,
                c.ocr_contains_any is not None,
                c.ocr_contains_all is not None,
                c.vision_label_gt is not None,
                c.filename_pattern_any is not None,
                c.has_exif_date is not None,
                c.has_camera_metadata is not None,
                c.exif_software_contains is not None,
                c.min_unique_colors is not None,
                c.max_unique_colors is not None,
                c.not_extensions is not None,
                c.not_filename_regex is not None,
                c.not_filename_pattern_any is not None,
                c.not_path_contains is not None,
                c.cascade_category_any is not None,
                c.cascade_status_any is not None,
                c.cascade_min_confidence is not None,
                c.cascade_stage_max is not None,
            ]
        )

    @staticmethod
    def _check_extensions(c, facts: FileFacts) -> ConditionCheck | None:
        if c.extensions is None:
            return None
        wanted = {ext.lower().lstrip(".") for ext in c.extensions}
        if facts.extension in wanted:
            return ConditionCheck(
                key="extension",
                passed=True,
                detail=f"extension '{facts.extension}' matches {sorted(wanted)}",
            )
        return ConditionCheck(
            key="extension",
            passed=False,
            detail=f"extension '{facts.extension}' not in {sorted(wanted)}",
        )

    @staticmethod
    def _check_mime(c, facts: FileFacts) -> ConditionCheck | None:
        if c.mime_prefixes is None:
            return None
        if any(facts.mime.startswith(prefix) for prefix in c.mime_prefixes):
            return ConditionCheck(
                key="mime",
                passed=True,
                detail=f"mime '{facts.mime}' matches prefixes {c.mime_prefixes}",
            )
        return ConditionCheck(
            key="mime",
            passed=False,
            detail=f"mime '{facts.mime}' does not match prefixes {c.mime_prefixes}",
        )

    @staticmethod
    def _check_filename_regex(c, facts: FileFacts) -> ConditionCheck | None:
        if c.filename_regex is None:
            return None
        name_nfc = _nfc(facts.filename)
        try:
            if re.search(c.filename_regex, name_nfc, re.IGNORECASE):
                return ConditionCheck(
                    key="filename",
                    passed=True,
                    detail=f"filename matches regex {c.filename_regex!r}",
                )
            return ConditionCheck(
                key="filename",
                passed=False,
                detail=f"filename does not match regex {c.filename_regex!r}",
            )
        except re.error as exc:
            return ConditionCheck(
                key="filename",
                passed=False,
                detail=f"invalid filename regex: {exc}",
            )

    @staticmethod
    def _check_path_contains(c, facts: FileFacts) -> ConditionCheck | None:
        if c.path_contains is None:
            return None
        path_text = _fold(str(facts.path))
        if all(_fold(token) in path_text for token in c.path_contains):
            return ConditionCheck(
                key="path",
                passed=True,
                detail=f"path contains tokens {c.path_contains}",
            )
        return ConditionCheck(
            key="path",
            passed=False,
            detail=f"path does not contain all tokens {c.path_contains}",
        )

    @staticmethod
    def _check_size_gt(c, facts: FileFacts) -> ConditionCheck | None:
        if c.size_gt is None:
            return None
        if facts.size > c.size_gt:
            return ConditionCheck(
                key="size_gt",
                passed=True,
                detail=f"size {facts.size} > {c.size_gt}",
            )
        return ConditionCheck(
            key="size_gt",
            passed=False,
            detail=f"size {facts.size} not > {c.size_gt}",
        )

    @staticmethod
    def _check_size_lt(c, facts: FileFacts) -> ConditionCheck | None:
        if c.size_lt is None:
            return None
        if facts.size < c.size_lt:
            return ConditionCheck(
                key="size_lt",
                passed=True,
                detail=f"size {facts.size} < {c.size_lt}",
            )
        return ConditionCheck(
            key="size_lt",
            passed=False,
            detail=f"size {facts.size} not < {c.size_lt}",
        )

    @staticmethod
    def _check_min_width(c, facts: FileFacts) -> ConditionCheck | None:
        if c.min_width is None:
            return None
        if facts.width is not None and facts.width >= c.min_width:
            return ConditionCheck(
                key="min_width",
                passed=True,
                detail=f"width {facts.width} >= {c.min_width}",
            )
        return ConditionCheck(
            key="min_width",
            passed=False,
            detail=(
                f"width {facts.width} not >= {c.min_width}"
                if facts.width is not None
                else "width unavailable"
            ),
        )

    @staticmethod
    def _check_min_height(c, facts: FileFacts) -> ConditionCheck | None:
        if c.min_height is None:
            return None
        if facts.height is not None and facts.height >= c.min_height:
            return ConditionCheck(
                key="min_height",
                passed=True,
                detail=f"height {facts.height} >= {c.min_height}",
            )
        return ConditionCheck(
            key="min_height",
            passed=False,
            detail=(
                f"height {facts.height} not >= {c.min_height}"
                if facts.height is not None
                else "height unavailable"
            ),
        )

    @staticmethod
    def _aspect(facts: FileFacts) -> float | None:
        if facts.width and facts.height:
            return float(facts.width) / float(facts.height)
        return None

    @staticmethod
    def _check_min_aspect(c, facts: FileFacts) -> ConditionCheck | None:
        if c.min_aspect is None:
            return None
        aspect = Engine._aspect(facts)
        if aspect is not None and aspect >= c.min_aspect:
            return ConditionCheck(
                key="min_aspect",
                passed=True,
                detail=f"aspect {aspect:.3f} >= {c.min_aspect}",
            )
        return ConditionCheck(
            key="min_aspect",
            passed=False,
            detail=(
                f"aspect {aspect:.3f} not >= {c.min_aspect}"
                if aspect is not None
                else "aspect unavailable"
            ),
        )

    @staticmethod
    def _check_max_aspect(c, facts: FileFacts) -> ConditionCheck | None:
        if c.max_aspect is None:
            return None
        aspect = Engine._aspect(facts)
        if aspect is not None and aspect <= c.max_aspect:
            return ConditionCheck(
                key="max_aspect",
                passed=True,
                detail=f"aspect {aspect:.3f} <= {c.max_aspect}",
            )
        return ConditionCheck(
            key="max_aspect",
            passed=False,
            detail=(
                f"aspect {aspect:.3f} not <= {c.max_aspect}"
                if aspect is not None
                else "aspect unavailable"
            ),
        )

    @staticmethod
    def _check_older_than_days(c, facts: FileFacts) -> ConditionCheck | None:
        if c.older_than_days is None:
            return None
        mtime = facts.mtime
        if mtime.tzinfo is None:
            mtime = mtime.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - mtime).total_seconds() / 86400.0
        if age_days >= float(c.older_than_days):
            return ConditionCheck(
                key="older_than_days",
                passed=True,
                detail=f"age {age_days:.1f}d >= {c.older_than_days}d",
            )
        return ConditionCheck(
            key="older_than_days",
            passed=False,
            detail=f"age {age_days:.1f}d not >= {c.older_than_days}d",
        )

    @staticmethod
    def _check_filename_pattern_any(c, facts: FileFacts) -> ConditionCheck | None:
        if c.filename_pattern_any is None:
            return None
        found = set(facts.features.get("filename_patterns", [])) & set(
            c.filename_pattern_any
        )
        if found:
            return ConditionCheck(
                key="filename_pattern",
                passed=True,
                detail=f"filename pattern {sorted(found)}",
            )
        return ConditionCheck(
            key="filename_pattern",
            passed=False,
            detail=f"filename patterns missing any of {c.filename_pattern_any}",
        )

    @staticmethod
    def _check_has_exif_date(c, facts: FileFacts) -> ConditionCheck | None:
        if c.has_exif_date is None:
            return None
        exif = facts.features.get("exif", {})
        if not isinstance(exif, dict):
            exif = {}
        present = bool(exif.get("datetime_original") or exif.get("datetime"))
        if present == c.has_exif_date:
            return ConditionCheck(
                key="has_exif_date",
                passed=True,
                detail=f"has_exif_date={c.has_exif_date}",
            )
        return ConditionCheck(
            key="has_exif_date",
            passed=False,
            detail=f"has_exif_date expected {c.has_exif_date}, got {present}",
        )

    @staticmethod
    def _check_has_camera_metadata(c, facts: FileFacts) -> ConditionCheck | None:
        if c.has_camera_metadata is None:
            return None
        exif = facts.features.get("exif", {})
        if not isinstance(exif, dict):
            exif = {}
        present = bool(exif.get("make") or exif.get("model"))
        if present == c.has_camera_metadata:
            return ConditionCheck(
                key="has_camera_metadata",
                passed=True,
                detail=f"has_camera_metadata={c.has_camera_metadata}",
            )
        return ConditionCheck(
            key="has_camera_metadata",
            passed=False,
            detail=(
                f"has_camera_metadata expected {c.has_camera_metadata}, "
                f"got {present}"
            ),
        )

    @staticmethod
    def _check_exif_software(c, facts: FileFacts) -> ConditionCheck | None:
        if c.exif_software_contains is None:
            return None
        exif = facts.features.get("exif", {})
        if not isinstance(exif, dict):
            exif = {}
        software = _fold(str(exif.get("software", "")))
        if any(_fold(t) in software for t in c.exif_software_contains):
            return ConditionCheck(
                key="exif_software",
                passed=True,
                detail=f"exif software matches {c.exif_software_contains}",
            )
        return ConditionCheck(
            key="exif_software",
            passed=False,
            detail=f"exif software does not match {c.exif_software_contains}",
        )

    @staticmethod
    def _check_max_unique_colors(c, facts: FileFacts) -> ConditionCheck | None:
        if c.max_unique_colors is None:
            return None
        unique = facts.features.get("unique_colors")
        if unique is not None and unique <= c.max_unique_colors:
            return ConditionCheck(
                key="max_unique_colors",
                passed=True,
                detail=f"unique_colors {unique} <= {c.max_unique_colors}",
            )
        return ConditionCheck(
            key="max_unique_colors",
            passed=False,
            detail=(
                f"unique_colors {unique} not <= {c.max_unique_colors}"
                if unique is not None
                else "unique_colors unavailable"
            ),
        )

    @staticmethod
    def _check_min_unique_colors(c, facts: FileFacts) -> ConditionCheck | None:
        if c.min_unique_colors is None:
            return None
        unique = facts.features.get("unique_colors")
        if unique is not None and unique >= c.min_unique_colors:
            return ConditionCheck(
                key="min_unique_colors",
                passed=True,
                detail=f"unique_colors {unique} >= {c.min_unique_colors}",
            )
        return ConditionCheck(
            key="min_unique_colors",
            passed=False,
            detail=(
                f"unique_colors {unique} not >= {c.min_unique_colors}"
                if unique is not None
                else "unique_colors unavailable"
            ),
        )

    @staticmethod
    def _check_not_extensions(c, facts: FileFacts) -> ConditionCheck | None:
        if c.not_extensions is None:
            return None
        blocked = {e.lower().lstrip(".") for e in c.not_extensions}
        if facts.extension in blocked:
            return ConditionCheck(
                key="not_extension",
                passed=False,
                detail=f"extension '{facts.extension}' is blocked",
            )
        return ConditionCheck(
            key="not_extension",
            passed=True,
            detail=f"extension not in {sorted(blocked)}",
        )

    @staticmethod
    def _check_not_filename_regex(c, facts: FileFacts) -> ConditionCheck | None:
        if c.not_filename_regex is None:
            return None
        name_nfc = _nfc(facts.filename)
        try:
            if re.search(c.not_filename_regex, name_nfc, re.IGNORECASE):
                return ConditionCheck(
                    key="not_filename",
                    passed=False,
                    detail=f"filename matches excluded regex {c.not_filename_regex!r}",
                )
            return ConditionCheck(
                key="not_filename",
                passed=True,
                detail=f"filename not match {c.not_filename_regex!r}",
            )
        except re.error as exc:
            return ConditionCheck(
                key="not_filename",
                passed=False,
                detail=f"invalid not_filename_regex: {exc}",
            )

    @staticmethod
    def _check_not_filename_pattern_any(
        c, facts: FileFacts
    ) -> ConditionCheck | None:
        if c.not_filename_pattern_any is None:
            return None
        found = set(facts.features.get("filename_patterns", [])) & set(
            c.not_filename_pattern_any
        )
        if found:
            return ConditionCheck(
                key="not_filename_pattern",
                passed=False,
                detail=f"filename pattern {sorted(found)} is excluded",
            )
        return ConditionCheck(
            key="not_filename_pattern",
            passed=True,
            detail=(
                "filename patterns exclude none of "
                f"{c.not_filename_pattern_any}"
            ),
        )

    @staticmethod
    def _check_not_path_contains(c, facts: FileFacts) -> ConditionCheck | None:
        if c.not_path_contains is None:
            return None
        path_text = _fold(str(facts.path))
        if any(_fold(t) in path_text for t in c.not_path_contains):
            return ConditionCheck(
                key="not_path",
                passed=False,
                detail=f"path contains excluded tokens {c.not_path_contains}",
            )
        return ConditionCheck(
            key="not_path",
            passed=True,
            detail=f"path not contains {c.not_path_contains}",
        )

    @staticmethod
    def _check_ocr(c, facts: FileFacts) -> list[ConditionCheck] | None:
        if c.ocr_contains_any is None and c.ocr_contains_all is None:
            return None

        ocr = facts.features.get("ocr")
        if not isinstance(ocr, dict):
            return [
                ConditionCheck(
                    key="ocr",
                    passed=False,
                    detail="OCR features unavailable",
                )
            ]

        text = _fold(str(ocr.get("text", "")))
        if not text:
            return [
                ConditionCheck(
                    key="ocr",
                    passed=False,
                    detail="OCR text empty",
                )
            ]

        checks: list[ConditionCheck] = []

        if c.ocr_contains_any is not None:
            if any(_fold(term) in text for term in c.ocr_contains_any):
                checks.append(
                    ConditionCheck(
                        key="ocr_any",
                        passed=True,
                        detail=f"OCR contains any of {c.ocr_contains_any}",
                    )
                )
            else:
                checks.append(
                    ConditionCheck(
                        key="ocr_any",
                        passed=False,
                        detail=f"OCR does not contain any of {c.ocr_contains_any}",
                    )
                )

        if c.ocr_contains_all is not None:
            if all(_fold(term) in text for term in c.ocr_contains_all):
                checks.append(
                    ConditionCheck(
                        key="ocr_all",
                        passed=True,
                        detail=f"OCR contains all of {c.ocr_contains_all}",
                    )
                )
            else:
                checks.append(
                    ConditionCheck(
                        key="ocr_all",
                        passed=False,
                        detail=f"OCR does not contain all of {c.ocr_contains_all}",
                    )
                )

        return checks

    @staticmethod
    def _check_vision(c, facts: FileFacts) -> list[ConditionCheck] | None:
        if c.vision_label_gt is None:
            return None

        vision = facts.features.get("vision")
        if not isinstance(vision, dict):
            return [
                ConditionCheck(
                    key="vision",
                    passed=False,
                    detail="vision features unavailable",
                )
            ]

        checks: list[ConditionCheck] = []
        for label, threshold in c.vision_label_gt.items():
            try:
                score = float(vision.get(label, 0.0))
            except (TypeError, ValueError):
                checks.append(
                    ConditionCheck(
                        key=f"vision.{label}",
                        passed=False,
                        detail=f"vision.{label} not a number",
                    )
                )
                continue

            if score >= threshold:
                checks.append(
                    ConditionCheck(
                        key=f"vision.{label}",
                        passed=True,
                        detail=f"vision.{label}={score:.3f} >= {threshold:.3f}",
                    )
                )
            else:
                checks.append(
                    ConditionCheck(
                        key=f"vision.{label}",
                        passed=False,
                        detail=f"vision.{label}={score:.3f} < {threshold:.3f}",
                    )
                )
        return checks

    @staticmethod
    def _check_cascade(c, facts: FileFacts) -> list[ConditionCheck] | None:
        """Evaluate cascade_* conditions against features['cascade']."""
        wants = (
            c.cascade_category_any is not None
            or c.cascade_status_any is not None
            or c.cascade_min_confidence is not None
            or c.cascade_stage_max is not None
        )
        if not wants:
            return None

        cascade = facts.features.get("cascade")
        if not isinstance(cascade, dict):
            return [
                ConditionCheck(
                    key="cascade",
                    passed=False,
                    detail="cascade features unavailable",
                )
            ]

        checks: list[ConditionCheck] = []

        if c.cascade_category_any is not None:
            category = str(cascade.get("category") or "")
            wanted = {_fold(x) for x in c.cascade_category_any}
            passed = _fold(category) in wanted
            checks.append(
                ConditionCheck(
                    key="cascade_category",
                    passed=passed,
                    detail=(
                        f"cascade.category={category!r} "
                        f"{'in' if passed else 'not in'} "
                        f"{sorted(c.cascade_category_any)}"
                    ),
                )
            )

        if c.cascade_status_any is not None:
            status = str(cascade.get("status") or "")
            wanted = {_fold(x) for x in c.cascade_status_any}
            passed = _fold(status) in wanted
            checks.append(
                ConditionCheck(
                    key="cascade_status",
                    passed=passed,
                    detail=(
                        f"cascade.status={status!r} "
                        f"{'in' if passed else 'not in'} "
                        f"{sorted(c.cascade_status_any)}"
                    ),
                )
            )

        if c.cascade_min_confidence is not None:
            try:
                conf = float(cascade.get("confidence") or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            threshold = float(c.cascade_min_confidence)
            passed = conf >= threshold
            checks.append(
                ConditionCheck(
                    key="cascade_min_confidence",
                    passed=passed,
                    detail=(
                        f"cascade.confidence={conf:.3f} "
                        f"{'>=' if passed else '<'} {threshold:.3f}"
                    ),
                )
            )

        if c.cascade_stage_max is not None:
            try:
                stage = int(cascade.get("stage_used"))
            except (TypeError, ValueError):
                stage = None
            limit = int(c.cascade_stage_max)
            passed = stage is not None and stage <= limit
            checks.append(
                ConditionCheck(
                    key="cascade_stage_max",
                    passed=passed,
                    detail=(
                        f"cascade.stage_used={stage} <= {limit}"
                        if passed
                        else (
                            f"cascade.stage_used={stage} not <= {limit}"
                            if stage is not None
                            else "cascade.stage_used unavailable"
                        )
                    ),
                )
            )

        return checks
