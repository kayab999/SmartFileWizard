from __future__ import annotations

import fcntl
import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .persist import atomic_write_text

logger = logging.getLogger(__name__)

# WP-D2 (F-11): how long an enqueue/mutation waits for the queue lock
# before failing explicitly. Long enough for a concurrent writer to
# finish; short enough that a wedged holder cannot freeze the GUI.
QUEUE_LOCK_TIMEOUT_S = 10.0
QUEUE_LOCK_POLL_S = 0.05


class ReviewQueueLockError(RuntimeError):
    """The queue lock could not be acquired within the timeout."""


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
        # Re-entrancy guard per thread: save() inside a transaction must
        # not try to re-acquire the flock (flock locks are per open file
        # description; a second fd in the same process would deadlock).
        self._tls = threading.local()
        # ids present at the last load: the basis for merge_new_items().
        self._loaded_ids: set[str] = set()
        self.load()

    # --- locking (WP-D2, F-11) ---------------------------------------------

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def _locked(self, timeout: float = QUEUE_LOCK_TIMEOUT_S) -> Iterator[Any]:
        """Exclusive inter-process lock on ``<queue>.lock`` (flock).

        Fails with ReviewQueueLockError after ``timeout`` instead of
        hanging a GUI thread forever.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.lock_path, "a+")
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ReviewQueueLockError(
                            f"review queue busy for over {timeout:.0f}s: "
                            f"{self.lock_path}"
                        ) from None
                    time.sleep(QUEUE_LOCK_POLL_S)
            yield fh
        finally:
            try:
                fcntl.flock(fh, fcntl.LOCK_UN)
            except OSError:
                pass
            fh.close()

    @contextmanager
    def transaction(
        self,
        *,
        reload: bool = True,
        save: bool = True,
        timeout: float = QUEUE_LOCK_TIMEOUT_S,
    ) -> Iterator["ReviewQueue"]:
        """Serialize load → mutate → save against other processes (F-11).

        Entry: acquire the lock, then (optionally) re-read the file so the
        mutation applies to the latest on-disk state, not a stale copy.
        Exit: persist — unless ``save=False`` (the caller saves explicitly
        inside the lock) or the body raised.

        ``reload`` replaces ``self.items`` with the fresh disk state;
        management mutators (resolve/delete/clear) are authoritative and
        use it; enqueue-only writers use ``merge_new_items`` instead so
        they never drop concurrent entries.
        """
        depth = getattr(self._tls, "depth", 0)
        with self._locked(timeout):
            self._tls.depth = depth + 1
            try:
                if reload:
                    self.load()
                yield self
                if save:
                    self._save_locked()
            finally:
                self._tls.depth = depth

    def _save_locked(self) -> None:
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

    def merge_new_items(self) -> int:
        """Commit in-memory additions without clobbering other writers.

        Reloads the disk state under the lock and appends only the items
        created since this object last loaded (unknown ids, not already
        covered by an unresolved path entry on disk). Concurrent adds,
        resolutions and deletions by other processes are preserved; this
        method never removes anything.
        """
        additions = [
            item for item in self.items if item.id not in self._loaded_ids
        ]
        added = 0
        with self.transaction(reload=True, save=False):
            known_ids = {item.id for item in self.items}
            for item in additions:
                if item.id in known_ids:
                    continue
                if any(
                    existing.path == item.path and not existing.resolved
                    for existing in self.items
                ):
                    continue  # disk already holds an unresolved entry
                self.items.append(item)
                known_ids.add(item.id)
                added += 1
            if added:
                self._save_locked()
        self._loaded_ids = {item.id for item in self.items}
        return added

    def load(self) -> None:
        self.load_error = None
        if not self.path.is_file():
            self.items = []
            self._loaded_ids = set()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = [ReviewItem(**row) for row in raw.get("items", [])]
            self._loaded_ids = {item.id for item in self.items}
        except Exception as exc:
            logger.warning("Review queue unreadable (%s): %s", self.path, exc)
            bak = self.path.with_name(self.path.name + ".bak")
            try:
                self.path.replace(bak)
                logger.warning("Corrupt queue moved to %s", bak)
            except OSError as move_exc:
                logger.warning("Could not quarantine corrupt queue: %s", move_exc)
            self.items = []
            self._loaded_ids = set()
            self.load_error = str(exc)

    def save(self) -> None:
        """Persist the queue (inter-process serialized)."""
        if getattr(self._tls, "depth", 0) > 0:
            self._save_locked()
            return
        with self._locked():
            self._save_locked()

    def pending(self) -> list[ReviewItem]:
        return [i for i in self.items if not i.resolved]

    def add_model_hold(self, path: Path, reason: str, *, save: bool = True) -> None:
        """Remember a file whose model match is not allowed to move it yet."""
        self.add(
            ReviewItem(
                id=uuid.uuid4().hex[:12],
                path=str(path),
                category_hint="unknown",
                reason=reason,
                status="unknown",
                created_at=datetime.now(timezone.utc).isoformat(),
            ),
            save=save,
        )

    def add(
        self, item: ReviewItem, *, dedupe_path: bool = True, save: bool = True
    ) -> None:
        """Append (or refresh) an item. Pass save=False to batch many adds
        and call merge_new_items()/save() once (I6: avoids O(U·Q) full
        rewrites per file).

        With save=True the whole add is serialized against other
        processes on fresh disk state (F-11): the dedupe check cannot
        miss an entry another process just wrote.
        """
        if not save:
            self._add_in_memory(item, dedupe_path=dedupe_path)
            return
        with self.transaction(reload=True):
            self._add_in_memory(item, dedupe_path=dedupe_path)

    def _add_in_memory(self, item: ReviewItem, *, dedupe_path: bool) -> None:
        if dedupe_path:
            for existing in self.items:
                if existing.path == item.path and not existing.resolved:
                    # Refresh hint
                    existing.category_hint = item.category_hint
                    existing.confidence = item.confidence
                    existing.status = item.status
                    existing.stage_used = item.stage_used
                    existing.reason = item.reason
                    return
        self.items.append(item)

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
        """Resolve on fresh disk state, serialized (F-11).

        The labels export is written inside the same lock so the labels
        file and the queue can never disagree about the resolution.
        """
        with self.transaction(reload=True, save=False):
            for item in self.items:
                if item.id == item_id:
                    item.resolved = True
                    item.resolved_category = category
                    item.resolved_at = datetime.now(timezone.utc).isoformat()
                    # I5: human confirmation is certain evidence —
                    # min_confidence rules must not reject it for a stale
                    # low score.
                    previous_confidence = item.confidence
                    item.confidence = 1.0
                    try:
                        self.persist_resolved_labels()
                    except OSError as exc:
                        item.resolved = False
                        item.resolved_category = None
                        item.resolved_at = None
                        item.confidence = previous_confidence
                        logger.warning("review_labels.json not written: %s", exc)
                        return False
                    self._save_locked()
                    return True
        return False

    def dismiss(self, item_id: str) -> bool:
        return self.resolve(item_id, "dismissed")

    def clear_resolved(self) -> int:
        removed = 0
        with self.transaction(reload=True):
            before = len(self.items)
            self.items = [i for i in self.items if not i.resolved]
            removed = before - len(self.items)
        return removed

    def delete(self, item_id: str) -> bool:
        """Hard-delete one item (pending or resolved), serialized (F-11)."""
        deleted = False
        with self.transaction(reload=True):
            before = len(self.items)
            self.items = [i for i in self.items if i.id != item_id]
            deleted = len(self.items) != before
        return deleted

    def purge_resolved(self, *, older_than_days: int = 90) -> int:
        """Delete resolved items older than the cutoff (retention, Fase 3)."""
        if older_than_days < 0:
            raise ValueError("older_than_days must be >= 0")
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=older_than_days)
        ).isoformat()
        removed = 0
        with self.transaction(reload=True):
            before = len(self.items)
            self.items = [
                i
                for i in self.items
                if not (i.resolved and (i.resolved_at or "") < cutoff)
            ]
            removed = before - len(self.items)
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
