from pathlib import Path

from filewizard.perception.config import (
    config_from_profile,
    load_perception_config,
    save_perception_config,
)
from filewizard.perception.http_openai import probe_server
from unittest.mock import patch
import urllib.error


def test_roundtrip_custom_models(tmp_path: Path) -> None:
    cfg = config_from_profile("recommended")
    cfg.ocr.model = "My-Custom-OCR"
    cfg.vision.model = "Qwen3-VL-4B-Instruct"
    cfg.vision.base_url = "http://127.0.0.1:9090/v1"
    path = save_perception_config(cfg, tmp_path / "perception.yaml")
    loaded = load_perception_config(path)
    assert loaded.ocr.model == "My-Custom-OCR"
    assert loaded.vision.model == "Qwen3-VL-4B-Instruct"
    assert "9090" in loaded.vision.base_url


def test_host_is_loopback() -> None:
    from filewizard.perception.http_openai import host_is_loopback

    assert host_is_loopback("http://127.0.0.1:8080/v1")
    assert host_is_loopback("http://localhost:8081/v1")
    assert not host_is_loopback("http://ocr.example.com/v1")


def test_hf_load_kwargs_default_no_download() -> None:
    from filewizard.perception.zeroshot import hf_load_kwargs

    assert hf_load_kwargs(allow_download=False) == {"local_files_only": True}
    assert hf_load_kwargs(allow_download=True) == {"local_files_only": False}


def test_probe_treats_405_as_ok() -> None:
    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="http://x/v1/models",
            code=405,
            msg="Method Not Allowed",
            hdrs=None,
            fp=None,
        )

    with patch("urllib.request.urlopen", side_effect=_raise):
        result = probe_server("http://127.0.0.1:8081/v1")
    assert result["ok"] is True
