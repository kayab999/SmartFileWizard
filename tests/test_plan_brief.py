from pathlib import Path

from filewizard.engine import ConditionCheck
from filewizard.executor import PlannedOperation
from filewizard.plan_brief import plan_brief, result_brief


def _op(
    name: str,
    dest: str,
    status: str = "planned",
    *,
    size: int | None = 100,
    collision: str = "append",
    rule: str = "pdfs",
) -> PlannedOperation:
    return PlannedOperation(
        source=Path("/tmp/in") / name,
        rule_id=rule,
        rule_name="PDFs",
        destination=Path(dest) / name,
        conditions=[
            ConditionCheck(key="extension", passed=True, detail="extensión pdf"),
        ],
        on_collision=collision,
        status=status,
        identity_size=size,
    )


def test_empty_plan_says_nothing_to_apply() -> None:
    assert plan_brief([]) == "No hay nada que aplicar."


def test_brief_states_source_volume_destination_rule_and_collision() -> None:
    text = plan_brief(
        [_op("a.pdf", "/docs/invoices", size=1024), _op("b.pdf", "/docs/invoices", size=1024)],
        source="/home/me/Downloads",
        scanned=4,
        scan_errors=["perm: denied"],
    )
    assert "Origen: /home/me/Downloads" in text
    assert "Archivos leídos: 4" in text
    assert "2 archivos" in text
    assert "2.0 KB" in text
    assert "/docs/invoices (2)" in text
    assert "Regla PDFs: extensión pdf" in text
    assert "si ya existe un archivo, se le cambia el nombre" in text
    assert "1 rutas no se pudieron leer." in text


def test_brief_omits_byte_total_when_a_size_is_missing() -> None:
    text = plan_brief(
        [_op("a.pdf", "/docs", size=10), _op("b.pdf", "/docs", size=None)]
    )
    assert text.startswith("2 archivos\n") or "\n2 archivos\n" in text
    assert "KB" not in text
    assert "B" not in text.split("2 archivos", 1)[1].split("\n", 1)[0]


def test_many_destinations_are_collapsed() -> None:
    ops = [_op(f"{i}.pdf", f"/docs/{i}", rule=f"r{i}") for i in range(5)]
    text = plan_brief(ops)
    assert "y 2 carpetas más" in text


def test_replace_and_held_files_are_named() -> None:
    text = plan_brief(
        [
            _op("a.pdf", "/docs", collision="replace"),
            _op("b.pdf", "/docs", status="stale", size=None),
            _op("c.pdf", "/docs", status="skipped", size=None),
        ]
    )
    assert "se sustituye" in text
    assert "El archivo que ya está ahí se guarda y el deshacer lo devuelve." in text
    assert "1 cambiaron después del plan" in text
    assert "1 se omiten" in text


def test_result_names_done_stale_error_and_undo() -> None:
    text = result_brief(
        [
            _op("a.pdf", "/docs", status="done"),
            _op("b.pdf", "/docs", status="stale"),
            _op("c.pdf", "/docs", status="error"),
        ]
    )
    assert "Hechos: 1" in text
    assert "El archivo cambió y no se movió: 1" in text
    assert "Con error: 1" in text
    assert "ventana principal" in text
