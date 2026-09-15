from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from ..facts import FeatureExtractor
from ..persist import atomic_write_text
from .config import PerceptionConfig
from .snapshot import compact_cache_features

logger = logging.getLogger(__name__)

# 0.9.4: files larger than this skip the perception cache entirely
# (no full hash — slow on multi-GB media, and a sampled hash could collide).
MAX_CACHE_FILE_BYTES = 64 * 1024 * 1024
MAX_CACHE_ENTRY_BYTES = 256 * 1024


def file_content_hash(path: Path) -> str:
    """SHA-256 of full file contents (stable identity for cache keys)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def config_fingerprint(config: PerceptionConfig) -> str:
    """Short hash of perception settings that affect extractor output."""
    payload = {
        "ocr": config.ocr.model_dump(mode="python"),
        "vision": config.vision.model_dump(mode="python"),
        "cascade": config.cascade.model_dump(mode="python"),
        "heuristics": config.heuristics,
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def default_cache_dir(state_dir: Path | None = None) -> Path:
    root = (state_dir or Path("~/.local/share/filewizard")).expanduser()
    return root / "perception_cache"


class PerceptionCache:
    """
    Disk cache of extractor feature dicts keyed by content hash + config.

    Layout: {cache_dir}/{key}.json
    Index:  {cache_dir}/index.json  → {key: mtime} for eviction.
    """

    def __init__(
        self,
        root: Path | None = None,
        *,
        state_dir: Path | None = None,
        max_entries: int = 5000,
        max_bytes: int = 64 * 1024 * 1024,
    ):
        self.root = root or default_cache_dir(state_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_entries = max(1, max_entries)
        self.max_bytes = max(1, max_bytes)
        self._index_path = self.root / "index.json"
        self._index: dict[str, float] = self._load_index()

    def _load_index(self) -> dict[str, float]:
        if not self._index_path.is_file():
            return {}
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {str(k): float(v) for k, v in raw.items()}
        except Exception as exc:
            logger.warning("cache index load failed: %s", exc)
        return {}

    def _save_index(self) -> None:
        atomic_write_text(
            self._index_path,
            json.dumps(self._index, indent=0),
        )

    def make_key(self, path: Path, *, config_fp: str, extractor: str) -> str:
        content = file_content_hash(path)
        raw = f"{content}|{config_fp}|{extractor}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.root / f"{key}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            self._index[key] = time.time()
            return data
        except Exception as exc:
            logger.debug("cache get failed for %s: %s", key, exc)
            return None

    def put(self, key: str, features: dict[str, Any]) -> None:
        if not features:
            return
        if not self._should_store(features):
            return
        compact = compact_cache_features(features)
        blob = json.dumps(compact, ensure_ascii=False, default=str)
        if len(blob.encode("utf-8")) > MAX_CACHE_ENTRY_BYTES:
            logger.warning("cache skip oversized entry %s", key[:12])
            return
        path = self.root / f"{key}.json"
        try:
            atomic_write_text(path, blob)
            self._index[key] = time.time()
            self._evict_if_needed()
            self._save_index()
        except Exception as exc:
            logger.warning("cache put failed for %s: %s", key, exc)

    @staticmethod
    def _should_store(features: dict[str, Any]) -> bool:
        cascade = features.get("cascade")
        if isinstance(cascade, dict) and cascade.get("status") == "error":
            return False
        errors = features.get("errors")
        if errors:
            return False
        return True

    def _payload_bytes(self) -> int:
        total = 0
        for path in self.root.glob("*.json"):
            if path.name == "index.json":
                continue
            try:
                total += path.stat().st_size
            except OSError:
                pass
        return total

    def _drop_key(self, key: str) -> None:
        path = self.root / f"{key}.json"
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
        self._index.pop(key, None)

    def _evict_if_needed(self) -> None:
        ordered = sorted(self._index.items(), key=lambda kv: kv[1])
        while len(self._index) > self.max_entries and ordered:
            key, _ = ordered.pop(0)
            self._drop_key(key)
        while self._payload_bytes() > self.max_bytes and self._index:
            if not ordered:
                ordered = sorted(self._index.items(), key=lambda kv: kv[1])
            if not ordered:
                break
            key, _ = ordered.pop(0)
            self._drop_key(key)

    def clear(self) -> int:
        n = 0
        for path in self.root.glob("*.json"):
            if path.name == "index.json":
                continue
            try:
                path.unlink()
                n += 1
            except OSError:
                pass
        self._index = {}
        self._save_index()
        return n


class CachingExtractor:
    """
    FeatureExtractor wrapper: disk-cache the inner extractor's dict output.

    Preserves inner.name for factory/status checks.
    """

    def __init__(
        self,
        inner: FeatureExtractor,
        cache: PerceptionCache,
        *,
        config_fp: str,
    ):
        self.inner = inner
        self.cache = cache
        self.config_fp = config_fp
        self.name = getattr(inner, "name", "cached")
        # I6: same-process memo (path, mtime_ns, size) → key. Skips the
        # full SHA-256 re-read on repeated ticks/runs while the file is
        # untouched. Cross-process still re-hashes (slow-correct default).
        self._memo: dict[tuple[str, int, int], str] = {}

    def _memo_key(self, path: Path) -> str | None:
        """Cache key via memo when mtime+size match, else full hash."""
        try:
            st = path.stat()
        except OSError:
            return None
        if st.st_size > MAX_CACHE_FILE_BYTES:
            logger.debug("cache skip large file %s", path)
            return None
        memo = (str(path), st.st_mtime_ns, st.st_size)
        hit = self._memo.get(memo)
        if hit is not None:
            return hit
        try:
            key = self.cache.make_key(
                path, config_fp=self.config_fp, extractor=self.name
            )
        except OSError as exc:
            logger.debug("cache key failed for %s: %s", path, exc)
            return None
        if len(self._memo) >= max(1, self.cache.max_entries):
            self._memo.clear()
        self._memo[memo] = key
        return key

    def extract(self, path: Path) -> dict[str, Any]:
        key = self._memo_key(path)
        if key is None:
            # Oversized, vanished, or unhashable: bypass cache entirely.
            return self.inner.extract(path)

        hit = self.cache.get(key)
        if hit is not None:
            # Annotate for debug/audit without changing rule semantics.
            if isinstance(hit.get("cascade"), dict):
                hit = dict(hit)
                cascade = dict(hit["cascade"])
                cascade["cache_hit"] = True
                hit["cascade"] = cascade
            else:
                hit = {**hit, "_cache_hit": True}
            return hit

        data = self.inner.extract(path)
        if isinstance(data, dict):
            self.cache.put(key, data)
        return data
