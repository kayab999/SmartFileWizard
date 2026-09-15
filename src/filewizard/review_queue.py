from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .persist import atomic_write_text

logger = logging.getLogger(__name__)


def review_badge_label(queue: ReviewQueue) -> str:
    """Home-button caption: pending count, or corrupt-queue warning."""
    if queue.load_error:
        return "Cola de revisión (corrupta)…"
    n = len(queue.pending())
    if n:
        return f"Cola de revisión ({n})…"
    return "Cola de revisión…"


def default_queue_path(state_dir: Path | None = None) -> Path:
    root = (state_dir or Path("~/.local/share/filewizard")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root / "review_queue.json"


@dataclass
class ReviewItem:
    id: str
    path: str
    category_hint: str = "unknown"
    confidence: float = 0.0
    status: str = "unknown"  # cascade status
    stage_used: int = 0
    reason: str = ""
    ocr_preview: str = ""
    created_at: str = ""
    # User resolution
    resolved: bool = False
    resolved_category: str | None = None
    resolved_at: str | None = None

    @staticmethod
    def from_cascade(
        path: Path,
        cascade: dict[str, Any],
        *,
        reason: str = "",
    ) -> ReviewItem:
        return ReviewItem(
            id=uuid.uuid4().hex[:12],
            path=str(path),
            category_hint=str(cascade.get("category") or "unknown"),
            confidence=float(cascade.get("confidence") or 0.0),
            status=str(cascade.get("status") or "unknown"),
            stage_used=int(cascade.get("stage_used") or 0),
            reason=reason or str(cascade.get("reasoning") or ""),
            ocr_preview="",
            created_at=datetime.now(timezone.utc).isoformat(),
        )


class ReviewQueue:
    """
    Persistent queue of files needing manual classification.

    JSON file under state_dir — simple, auditable, no DB migration.
    """

    def __init__(self, path: Path | None = None, state_dir: Path | None = None):
        self.path = path or default_queue_path(state_dir)
        self.items: list[ReviewItem] = []
        self.load_error: str | None = None
        self.load()

    def load(self) -> None:
        self.load_error = None
        if not self.path.is_file():
            self.items = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = [ReviewItem(**row) for row in raw.get("items", [])]
        except Exception as exc:
            logger.warning("Review queue unreadable (%s): %s", self.path, exc)
            bak = self.path.with_name(self.path.name + ".bak")
            try:
                self.path.replace(bak)
                logger.warning("Corrupt queue moved to %s", bak)
            except OSError as move_exc:
                logger.warning("Could not quarantine corrupt queue: %s", move_exc)
            self.items = []
            self.load_error = str(exc)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": [asdict(i) for i in self.items],
        }
        atomic_write_text(
            self.path,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

    def pending(self) -> list[ReviewItem]:
        return [i for i in self.items if not i.resolved]

    def add(
        self, item: ReviewItem, *, dedupe_path: bool = True, save: bool = True
    ) -> None:
        """Append (or refresh) an item. Pass save=False to batch many adds
        and call save() once (I6: avoids O(U·Q) full rewrites per file)."""
        if dedupe_path:
            for existing in self.items:
                if existing.path == item.path and not existing.resolved:
                    # Refresh hint
                    existing.category_hint = item.category_hint
                    existing.confidence = item.confidence
                    existing.status = item.status
                    existing.stage_used = item.stage_used
                    existing.reason = item.reason
                    if save:
                        self.save()
                    return
        self.items.append(item)
        if save:
            self.save()

    def add_from_features(
        self,
        path: Path,
        features: dict[str, Any],
        *,
        only_if_needs_review: bool = True,
        save: bool = True,
    ) -> ReviewItem | None:
        cascade = features.get("cascade") or {}
        status = str(cascade.get("status") or "")
        conf = float(cascade.get("confidence") or 0.0)
        needs = status in {"unknown", "rejected"} or (
            status == "probable" and conf < 0.65
        )
        if only_if_needs_review and not needs:
            return None
        ocr = features.get("ocr") or {}
        item = ReviewItem.from_cascade(
            path,
            cascade,
            reason=f"status={status} conf={conf:.2f}",
        )
        item.ocr_preview = str(ocr.get("text") or "")[:200]
        self.add(item, save=save)
        return item

    def resolve(self, item_id: str, category: str) -> bool:
        for item in self.items:
            if item.id == item_id:
                item.resolved = True
                item.resolved_category = category
                item.resolved_at = datetime.now(timezone.utc).isoformat()
                # I5: human confirmation is certain evidence — min_confidence
                # rules must not reject it for a stale low score.
                item.confidence = 1.0
                self.save()
                try:
                    self.persist_resolved_labels()
                except OSError as exc:
                    logger.warning("review_labels.json not written: %s", exc)
                return True
        return False

    def dismiss(self, item_id: str) -> bool:
        return self.resolve(item_id, "dismissed")

    def clear_resolved(self) -> int:
        before = len(self.items)
        self.items = [i for i in self.items if not i.resolved]
        self.save()
        return before - len(self.items)

    def delete(self, item_id: str) -> bool:
        """Hard-delete one item (pending or resolved)."""
        before = len(self.items)
        self.items = [i for i in self.items if i.id != item_id]
        if len(self.items) == before:
            return False
        self.save()
        return True

    def purge_resolved(self, *, older_than_days: int = 90) -> int:
        """Delete resolved items older than the cutoff (retention, Fase 3)."""
        if older_than_days < 0:
            raise ValueError("older_than_days must be >= 0")
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=older_than_days)
        ).isoformat()
        before = len(self.items)
        self.items = [
            i
            for i in self.items
            if not (i.resolved and (i.resolved_at or "") < cutoff)
        ]
        removed = before - len(self.items)
        if removed:
            self.save()
        return removed

    def persist_resolved_labels(self) -> Path:
        """WP-0.11.2: write resolved labels for the next plan (agent-inject shape)."""
        from .persist import atomic_write_text

        dest = self.path.parent / "review_labels.json"
        payload = self.export_agent_labels(resolved_only=True)
        atomic_write_text(
            dest,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        return dest

    def export_agent_labels(self, *, resolved_only: bool = False) -> dict[str, dict]:
        """Mapping path → cascade features (WP-0.5.3 / MCP inject shape).

        I5: unresolved "unknown" is skipped (injecting it is a no-op for
        category rules); vision scores mirror the cascade category so
        vision_label_gt rules also fire from review export.
        """
        from .perception.cascade import LABEL_TO_VISION_KEY

        mapping: dict[str, dict] = {}
        for item in self.items:
            if resolved_only and not item.resolved:
                continue
            cat = item.resolved_category if item.resolved else item.category_hint
            if not cat or cat == "dismissed":
                continue
            if not item.resolved and cat == "unknown":
                continue
            vkey = LABEL_TO_VISION_KEY.get(cat, cat)
            mapping[item.path] = {
                "cascade": {
                    "category": cat,
                    "status": "confirmed" if item.resolved else item.status,
                    "confidence": item.confidence,
                    "stage_used": item.stage_used,
                    "reasoning": item.reason,
                },
                "vision": {vkey: item.confidence, "provider": "review"},
            }
        return mapping
