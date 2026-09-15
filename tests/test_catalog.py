from click.testing import CliRunner
from pytest import raises

from filewizard.cli import cli
from filewizard.perception.catalog import VALID_ROLES, list_known_models


def test_catalog_contains_expected_models() -> None:
    rows = list_known_models()
    by_id = {item["id"]: item for item in rows}
    assert by_id["glm-ocr"]["default_model"] == "GLM-OCR-Q8_0"
    assert by_id["qwen3-vl-2b"]["default_model"] == "Qwen3-VL-2B-Instruct"
    assert by_id["clip-vit-base-patch32"]["default_model"].startswith(
        "openai/clip-"
    )
    assert all(item["role"] in VALID_ROLES for item in rows)


def test_list_known_models_ocr_excludes_vision() -> None:
    ocr_rows = list_known_models("ocr")
    assert ocr_rows
    assert all(item["role"] == "ocr" for item in ocr_rows)
    assert "qwen3-vl-2b" in {item["id"] for item in ocr_rows}

    vision_rows = list_known_models("vision")
    assert all(item["role"] == "vision" for item in vision_rows)


def test_list_known_models_invalid_role_raises() -> None:
    with raises(ValueError):
        list_known_models("not-a-role")


def test_list_known_models_returns_copies() -> None:
    rows = list_known_models("ocr")
    rows[0]["id"] = "mutated"
    assert all(item["id"] != "mutated" for item in list_known_models("ocr"))


def test_cli_perception_models_no_network() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["perception", "models"])
    assert result.exit_code == 0, result.output
    assert "GLM-OCR-Q8_0" in result.output
    assert "Qwen3-VL-2B-Instruct" in result.output
    assert "openai/clip-vit-base-patch32" in result.output
    assert "ocr" in result.output and "vision" in result.output

    filtered = runner.invoke(cli, ["perception", "models", "--role", "ocr"])
    assert filtered.exit_code == 0, filtered.output
    assert "GLM-OCR-Q8_0" in filtered.output
    assert "zeroshot" not in filtered.output