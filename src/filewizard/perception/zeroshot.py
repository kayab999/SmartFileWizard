from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# English prompts for CLIP/SigLIP zero-shot (models usually English-centric).
LABEL_PROMPTS: dict[str, str] = {
    "factura": "a photo of an invoice or bill document",
    "recibo": "a photo of a receipt or ticket",
    "documento_escaneado": "a scanned document page",
    "formulario": "a filled form document",
    "captura_pantalla": "a computer or phone screenshot",
    "foto_persona": "a photograph of a person",
    "foto_paisaje": "a landscape photograph",
    "foto_producto": "a product photo",
    "meme": "an internet meme with text overlay",
    "grafico": "a chart or graph",
    "diapositiva": "a presentation slide",
    "interfaz_web": "a web page or app user interface",
    "codigo": "source code on a screen",
}


def zeroshot_available() -> bool:
    try:
        import transformers  # noqa: F401
        import torch  # noqa: F401
        from PIL import Image  # noqa: F401

        return True
    except ImportError:
        return False


class ZeroShotClassifier:
    """
    Stage-1 zero-shot image classifier (CLIP or SigLIP via transformers).

    Optional extra: pip install filewizard[zeroshot]
    Lazy-loads the model on first call.
    """

    def __init__(
        self,
        model_id: str = "openai/clip-vit-base-patch32",
        device: str | None = None,
        *,
        allow_download: bool = False,
        batch_size: int = 1,
    ):
        self.model_id = model_id
        self.device = device
        self.allow_download = allow_download
        self.batch_size = batch_size
        self._model = None
        self._processor = None
        self._torch = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModel, AutoProcessor

        self._torch = torch
        dev = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.device = dev
        load_kw = hf_load_kwargs(allow_download=self.allow_download)
        logger.info(
            "Loading zero-shot model %s on %s (download=%s)",
            self.model_id,
            dev,
            self.allow_download,
        )
        self._processor = AutoProcessor.from_pretrained(self.model_id, **load_kw)
        # CLIPModel / SiglipModel both work with similar API for this use.
        try:
            from transformers import CLIPModel

            self._model = CLIPModel.from_pretrained(self.model_id, **load_kw)
        except Exception as exc:
            logger.warning(
                "CLIP load failed for %s (%s); trying AutoModel fallback",
                self.model_id,
                exc,
            )
            self._model = AutoModel.from_pretrained(self.model_id, **load_kw)
        assert self._model is not None
        self._model.to(dev)
        self._model.eval()

    def predict(
        self,
        path: Path,
        labels: list[str],
    ) -> list[dict[str, Any]]:
        """
        Return list of {label, score} sorted by score descending.
        """
        from PIL import Image

        self._ensure_loaded()
        assert self._model is not None and self._processor is not None
        torch = self._torch

        texts = [LABEL_PROMPTS.get(lab, f"a photo of {lab}") for lab in labels]
        image = Image.open(path).convert("RGB")

        inputs = self._processor(
            text=texts,
            images=image,
            return_tensors="pt",
            padding=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            if hasattr(self._model, "get_image_features"):
                # CLIP-style
                image_features = self._model.get_image_features(
                    **{k: v for k, v in inputs.items() if k.startswith("pixel")}
                )
                text_features = self._model.get_text_features(
                    **{
                        k: v
                        for k, v in inputs.items()
                        if k in ("input_ids", "attention_mask")
                    }
                )
                image_features = image_features / image_features.norm(
                    dim=-1, keepdim=True
                )
                text_features = text_features / text_features.norm(
                    dim=-1, keepdim=True
                )
                logits = (image_features @ text_features.T) * 100.0
                probs = logits.softmax(dim=-1)[0]
            else:
                outputs = self._model(**inputs)
                logits = getattr(outputs, "logits_per_image", None)
                if logits is None:
                    raise RuntimeError(
                        f"Model {self.model_id} does not expose CLIP-like scores"
                    )
                probs = logits.softmax(dim=-1)[0]

        scored = [
            {"label": labels[i], "score": float(probs[i].item())}
            for i in range(len(labels))
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def predict_batch(
        self,
        paths: list[Path],
        labels: list[str],
    ) -> dict[Path, list[dict[str, Any]]]:
        """Classify several images in batched forward passes (A1).

        Results per path are identical to calling :meth:`predict`
        individually (same softmax over the same label set); the win is
        GPU/CPU throughput on the vision tower, not a different model.
        """
        from PIL import Image

        self._ensure_loaded()
        assert self._model is not None and self._processor is not None
        torch = self._torch

        results: dict[Path, list[dict[str, Any]]] = {}
        texts = [LABEL_PROMPTS.get(lab, f"a photo of {lab}") for lab in labels]
        paths = [Path(p) for p in paths]
        for start in range(0, len(paths), max(1, self.batch_size)):
            chunk = paths[start : start + self.batch_size]
            images = [Image.open(p).convert("RGB") for p in chunk]
            inputs = self._processor(
                text=texts,
                images=images,
                return_tensors="pt",
                padding=True,
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                if hasattr(self._model, "get_image_features"):
                    image_features = self._model.get_image_features(
                        **{
                            k: v
                            for k, v in inputs.items()
                            if k.startswith("pixel")
                        }
                    )
                    text_features = self._model.get_text_features(
                        **{
                            k: v
                            for k, v in inputs.items()
                            if k in ("input_ids", "attention_mask")
                        }
                    )
                    image_features = image_features / image_features.norm(
                        dim=-1, keepdim=True
                    )
                    text_features = text_features / text_features.norm(
                        dim=-1, keepdim=True
                    )
                    # [n_images, n_labels]
                    logits = (image_features @ text_features.T) * 100.0
                    probs = logits.softmax(dim=-1)
                else:
                    outputs = self._model(**inputs)
                    logits = getattr(outputs, "logits_per_image", None)
                    if logits is None:
                        raise RuntimeError(
                            f"Model {self.model_id} does not expose "
                            "CLIP-like scores"
                        )
                    probs = logits.softmax(dim=-1)
            for row, path in enumerate(chunk):
                scored = [
                    {"label": labels[i], "score": float(probs[row, i].item())}
                    for i in range(len(labels))
                ]
                scored.sort(key=lambda x: x["score"], reverse=True)
                results[path] = scored
        return results


def hf_load_kwargs(*, allow_download: bool) -> dict[str, bool]:
    """HuggingFace from_pretrained flags. Download is opt-in (no silent GB)."""
    return {"local_files_only": not allow_download}


def make_zeroshot_fn(
    model_id: str = "openai/clip-vit-base-patch32",
    *,
    allow_download: bool = False,
) -> Callable[[Path, list[str]], list[dict[str, Any]]] | None:
    """Return a zeroshot callable or None if deps missing."""
    if not zeroshot_available():
        return None
    clf = ZeroShotClassifier(model_id=model_id, allow_download=allow_download)

    def _fn(path: Path, labels: list[str]) -> list[dict[str, Any]]:
        return clf.predict(path, labels)

    return _fn


def make_zeroshot_batch_fn(
    model_id: str = "openai/clip-vit-base-patch32",
    *,
    allow_download: bool = False,
    batch_size: int = 8,
) -> Callable[[list[Path], list[str]], dict[Path, list[dict[str, Any]]]] | None:
    """Return a batched zeroshot callable (A1) or None if deps missing."""
    if not zeroshot_available():
        return None
    clf = ZeroShotClassifier(
        model_id=model_id,
        allow_download=allow_download,
        batch_size=batch_size,
    )

    def _fn(
        paths: list[Path], labels: list[str]
    ) -> dict[Path, list[dict[str, Any]]]:
        return clf.predict_batch(paths, labels)

    return _fn


class Stage1BatchQueue:
    """Buffer stage-1 requests and evaluate them in model-sized batches.

    The cascade works per file; this queue collects pending paths and, once
    ``batch_size`` requests accumulate (or ``flush`` is called), evaluates
    them in a single batched forward pass. Deterministic: results are handed
    back per path in request order via ``result(path)``.
    """

    def __init__(
        self,
        classifier: ZeroShotClassifier,
        labels: list[str],
        *,
        batch_size: int = 8,
    ) -> None:
        self.classifier = classifier
        self.labels = list(labels)
        self.batch_size = max(1, batch_size)
        self._pending: list[Path] = []
        self._results: dict[Path, list[dict[str, Any]]] = {}

    def request(self, path: Path) -> list[dict[str, Any]] | None:
        """Queue *path*; return its scores if already evaluated."""
        path = Path(path)
        if path in self._results:
            return self._results[path]
        if path not in self._pending:
            self._pending.append(path)
        if len(self._pending) >= self.batch_size:
            self.flush()
            return self._results.get(path)
        return None

    def flush(self) -> None:
        """Evaluate all pending paths in batched passes."""
        if not self._pending:
            return
        batch = self.classifier.predict_batch(self._pending, self.labels)
        self._results.update(batch)
        self._pending.clear()

    def result(self, path: Path) -> list[dict[str, Any]] | None:
        return self._results.get(Path(path))
