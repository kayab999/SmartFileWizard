from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..perception.config import (
    PROFILES,
    PerceptionConfig,
    config_from_profile,
    default_config_path,
    load_perception_config,
    save_perception_config,
)
from ..perception.factory import perception_status


class PerceptionSettingsDialog(QDialog):
    """Edit perception.yaml: profile, OCR/vision URLs and models."""

    def __init__(self, state_dir: Path, parent=None):
        super().__init__(parent)
        self.state_dir = state_dir
        self.setWindowTitle("Ajustes de percepción")
        self.resize(640, 640)

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)

        intro = QLabel(
            "Defaults de producto: GLM-OCR (:8080) + Qwen3-VL-2B (:8081). "
            "Cambia modelo o URL si tu hardware lo permite. "
            "Los pesos no se empaquetan en FileWizard. "
            "OCR/VLM del wizard fuerzan etapas 2/3; la cascada en Ajustes decide el resto."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        cat_row = QHBoxLayout()
        self.catalog_role = QComboBox()
        self.catalog_role.setAccessibleName("Rol del catálogo")
        from ..perception.catalog import VALID_ROLES

        for role in VALID_ROLES:
            self.catalog_role.addItem(role, role)
        self.catalog_model = QComboBox()
        self.catalog_model.setAccessibleName("Modelo del catálogo")
        self.catalog_role.currentIndexChanged.connect(self._refill_catalog)
        fill_btn = QPushButton("Rellenar campos")
        fill_btn.setAccessibleName("Rellenar campos desde el catálogo")
        fill_btn.setToolTip("Copia model/URL del catálogo a OCR, visión o zero-shot")
        fill_btn.clicked.connect(self._fill_from_catalog)
        cat_row.addWidget(QLabel("Catálogo:"))
        cat_row.addWidget(self.catalog_role)
        cat_row.addWidget(self.catalog_model, 1)
        cat_row.addWidget(fill_btn)
        layout.addLayout(cat_row)
        self._refill_catalog()

        form = QFormLayout()
        self.profile = QComboBox()
        self.profile.setAccessibleName("Perfil de percepción")
        self.profile.addItem("(personalizado / archivo)", "")
        for name in sorted(PROFILES):
            self.profile.addItem(name, name)
        self.profile.currentIndexChanged.connect(self._on_profile_changed)
        form.addRow("Perfil", self.profile)

        self.heuristics = QCheckBox("Heurísticas (EXIF, patrones, paleta)")
        self.heuristics.setChecked(True)
        form.addRow(self.heuristics)
        layout.addLayout(form)

        # Cascade thresholds
        cas_box = QGroupBox(
            "Cascada (barato primero → OCR → VLM solo si hace falta)"
        )
        cas_form = QFormLayout(cas_box)
        self.cascade_enabled = QCheckBox(
            "Activar cascada (recomendado con perfil recommended)"
        )
        self.high_conf = QDoubleSpinBox()
        self.high_conf.setRange(0.0, 1.0)
        self.high_conf.setSingleStep(0.05)
        self.high_conf.setValue(0.75)
        self.med_conf = QDoubleSpinBox()
        self.med_conf.setRange(0.0, 1.0)
        self.med_conf.setSingleStep(0.05)
        self.med_conf.setValue(0.50)
        self.vlm_conf = QDoubleSpinBox()
        self.vlm_conf.setRange(0.0, 1.0)
        self.vlm_conf.setSingleStep(0.05)
        self.vlm_conf.setValue(0.70)
        self.stage1 = QCheckBox(
            "Etapa 1: zero-shot (CLIP/SigLIP — pip install filewizard[zeroshot])"
        )
        self.stage1.setChecked(True)
        self.allow_model_download = QCheckBox(
            "Permitir descarga de pesos CLIP/SigLIP (HuggingFace; cientos de MB)"
        )
        self.allow_model_download.setChecked(False)
        self.zeroshot_model = QLineEdit("openai/clip-vit-base-patch32")
        self.stage2 = QCheckBox("Etapa 2: OCR (GLM-OCR / Tesseract)")
        self.stage2.setChecked(True)
        self.stage3 = QCheckBox("Etapa 3: VLM JSON (Qwen3-VL)")
        self.stage3.setChecked(True)
        cas_form.addRow(self.cascade_enabled)
        cas_form.addRow("Confianza alta (decide en etapa 1)", self.high_conf)
        cas_form.addRow("Confianza media (pasa a etapa 2)", self.med_conf)
        cas_form.addRow("Mínimo VLM (si no → unknown)", self.vlm_conf)
        cas_form.addRow(self.stage1)
        cas_form.addRow(self.allow_model_download)
        cas_form.addRow("Modelo zero-shot", self.zeroshot_model)
        cas_form.addRow(self.stage2)
        cas_form.addRow(self.stage3)
        self.cache_enabled = QCheckBox(
            "Cache de percepción (hash de archivo → features en disco)"
        )
        self.cache_enabled.setChecked(True)
        cas_form.addRow(self.cache_enabled)
        note = QLabel(
            "Etapa 0 = heurísticas (ms). Etapa 1 = CLIP/SigLIP (opcional). "
            "Etapa 2 = OCR. Etapa 3 = VLM. Ver docs/PLAN_CASCADE.md."
        )
        note.setWordWrap(True)
        cas_form.addRow(note)
        layout.addWidget(cas_box)

        # OCR
        ocr_box = QGroupBox("OCR (etapa 2) — default GLM-OCR")
        ocr_form = QFormLayout(ocr_box)
        self.ocr_provider = QComboBox()
        self.ocr_provider.addItems(["none", "tesseract", "llama_http"])
        self.ocr_url = QLineEdit("http://127.0.0.1:8080/v1")
        self.ocr_model = QLineEdit("GLM-OCR-Q8_0")
        ocr_form.addRow("Provider", self.ocr_provider)
        ocr_form.addRow("Base URL", self.ocr_url)
        ocr_form.addRow("Modelo", self.ocr_model)
        layout.addWidget(ocr_box)

        # Vision
        vis_box = QGroupBox("Visión / VLM (etapa 3) — default Qwen3-VL-2B")
        vis_form = QFormLayout(vis_box)
        self.vis_provider = QComboBox()
        self.vis_provider.addItems(["none", "llama_http"])
        self.vis_url = QLineEdit("http://127.0.0.1:8081/v1")
        self.vis_model = QLineEdit("Qwen3-VL-2B-Instruct")
        vis_form.addRow("Provider", self.vis_provider)
        vis_form.addRow("Base URL", self.vis_url)
        vis_form.addRow("Modelo", self.vis_model)
        layout.addWidget(vis_box)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        row = QHBoxLayout()
        probe_btn = QPushButton("Comprobar endpoints")
        probe_btn.clicked.connect(self.probe)
        reload_btn = QPushButton("Recargar archivo")
        reload_btn.clicked.connect(self.load_from_disk)
        row.addWidget(probe_btn)
        row.addWidget(reload_btn)
        row.addStretch()
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        path = default_config_path(self.state_dir)
        hint = QLabel(f"Archivo: {path}")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self.load_from_disk()

    def _refill_catalog(self) -> None:
        from ..perception.catalog import list_known_models

        role = str(self.catalog_role.currentData() or "ocr")
        self.catalog_model.clear()
        for item in list_known_models(role):
            label = f"{item['id']} · {item['default_model']}"
            self.catalog_model.addItem(label, item)

    def _fill_from_catalog(self) -> None:
        item = self.catalog_model.currentData()
        if not isinstance(item, dict):
            return
        role = item.get("role")
        model = str(item.get("default_model") or "")
        url = item.get("default_base_url") or ""
        if role == "ocr":
            if url:
                self.ocr_provider.setCurrentText("llama_http")
                self.ocr_url.setText(str(url))
            self.ocr_model.setText(model)
        elif role == "vision":
            if url:
                self.vis_provider.setCurrentText("llama_http")
                self.vis_url.setText(str(url))
            self.vis_model.setText(model)
        elif role == "zeroshot":
            self.zeroshot_model.setText(model)
            self.stage1.setChecked(True)

    def load_from_disk(self) -> None:
        cfg = load_perception_config(state_dir=self.state_dir)
        self._apply_config(cfg)

    def _apply_config(self, cfg: PerceptionConfig) -> None:
        idx = self.profile.findData(cfg.profile or "")
        if idx < 0:
            idx = 0
        self.profile.blockSignals(True)
        self.profile.setCurrentIndex(idx)
        self.profile.blockSignals(False)

        self.heuristics.setChecked(cfg.heuristics)

        self.cascade_enabled.setChecked(cfg.cascade.enabled)
        self.high_conf.setValue(cfg.cascade.high_confidence)
        self.med_conf.setValue(cfg.cascade.medium_confidence)
        self.vlm_conf.setValue(cfg.cascade.vlm_min_confidence)
        self.stage1.setChecked(cfg.cascade.enable_stage1)
        self.allow_model_download.setChecked(cfg.cascade.allow_model_download)
        self.zeroshot_model.setText(cfg.cascade.zeroshot_model)
        self.stage2.setChecked(cfg.cascade.enable_stage2)
        self.stage3.setChecked(cfg.cascade.enable_stage3)
        self.cache_enabled.setChecked(cfg.cache.enabled)

        oi = self.ocr_provider.findText(cfg.ocr.provider)
        self.ocr_provider.setCurrentIndex(max(0, oi))
        self.ocr_url.setText(cfg.ocr.base_url)
        self.ocr_model.setText(cfg.ocr.model)

        vi = self.vis_provider.findText(cfg.vision.provider)
        self.vis_provider.setCurrentIndex(max(0, vi))
        self.vis_url.setText(cfg.vision.base_url)
        self.vis_model.setText(cfg.vision.model)

        self._refresh_status(cfg)

    def _on_profile_changed(self) -> None:
        name = self.profile.currentData()
        if not name:
            return
        try:
            cfg = config_from_profile(str(name))
        except ValueError:
            return
        self._apply_config(cfg)

    def _build_config(self) -> PerceptionConfig:
        profile = self.profile.currentData() or None
        return PerceptionConfig(
            version=1,
            profile=profile if profile else None,
            heuristics=self.heuristics.isChecked(),
            cascade={
                "enabled": self.cascade_enabled.isChecked(),
                "high_confidence": self.high_conf.value(),
                "medium_confidence": self.med_conf.value(),
                "vlm_min_confidence": self.vlm_conf.value(),
                "enable_stage1": self.stage1.isChecked(),
                "allow_model_download": self.allow_model_download.isChecked(),
                "enable_stage2": self.stage2.isChecked(),
                "enable_stage3": self.stage3.isChecked(),
                "zeroshot_model": self.zeroshot_model.text().strip()
                or "openai/clip-vit-base-patch32",
            },
            cache={
                "enabled": self.cache_enabled.isChecked(),
            },
            ocr={
                "provider": self.ocr_provider.currentText(),
                "base_url": self.ocr_url.text().strip(),
                "model": self.ocr_model.text().strip(),
            },
            vision={
                "provider": self.vis_provider.currentText(),
                "base_url": self.vis_url.text().strip(),
                "model": self.vis_model.text().strip(),
            },
        )

    def _refresh_status(self, cfg: PerceptionConfig | None = None) -> None:
        cfg = cfg or self._build_config()
        st = perception_status(cfg, state_dir=self.state_dir)
        cas = st.get("cascade") or {}
        lines = [
            f"Perfil: {st.get('profile') or 'personalizado'}",
            f"Cascada: {'ON' if cas.get('enabled') else 'OFF'}"
            + (
                f" (alta={cas.get('high_confidence')}, "
                f"media={cas.get('medium_confidence')})"
                if cas.get("enabled")
                else ""
            ),
            f"OCR: {st['ocr']['provider']}"
            + (f" · {st['ocr'].get('model')}" if st["ocr"].get("model") else ""),
            f"Visión: {st['vision']['provider']}"
            + (
                f" · {st['vision'].get('model')}"
                if st["vision"].get("model")
                else ""
            ),
        ]
        zs = st.get("zeroshot")
        if zs is not None:
            lines.append(
                f"Zero-shot: {'disponible' if zs.get('available') else 'no instalado'}"
                f" · {zs.get('model') or ''}"
            )
        cache = st.get("cache") or {}
        lines.append(
            f"Cache: {'ON' if cache.get('enabled') else 'OFF'}"
            + (f" (máx {cache.get('max_entries')})" if cache.get("enabled") else "")
        )
        for name, ep in (st.get("endpoints") or {}).items():
            if ep.get("ok"):
                lines.append(f"● {name}: OK")
            else:
                lines.append(f"○ {name}: no disponible — {ep.get('error', '')[:80]}")
        self.status_label.setText("\n".join(lines))

    def probe(self) -> None:
        self._refresh_status()
        QMessageBox.information(
            self,
            "FileWizard",
            self.status_label.text(),
        )

    def save(self) -> None:
        try:
            cfg = self._build_config()
            remote = []
            from ..perception.http_openai import host_is_loopback

            if cfg.ocr.provider == "llama_http" and not host_is_loopback(
                cfg.ocr.base_url
            ):
                remote.append(f"OCR {cfg.ocr.base_url}")
            if cfg.vision.provider == "llama_http" and not host_is_loopback(
                cfg.vision.base_url
            ):
                remote.append(f"visión {cfg.vision.base_url}")
            if remote:
                QMessageBox.warning(
                    self,
                    "FileWizard",
                    "Las imágenes se enviarán (base64) fuera de este equipo:\n"
                    + "\n".join(remote),
                )
            path = save_perception_config(cfg, state_dir=self.state_dir)
        except Exception as exc:
            QMessageBox.critical(self, "FileWizard", f"No se pudo guardar:\n{exc}")
            return
        self._refresh_status(cfg)
        QMessageBox.information(
            self,
            "FileWizard",
            f"Configuración guardada en:\n{path}",
        )
        self.accept()
