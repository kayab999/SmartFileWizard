# Implementer Brief — OpenCode / DeepSeek V4

**Léeme primero.** Este archivo es la puerta de entrada al repo para codificación.

**Producto:** FileWizard · **versión baseline:** `0.11.0`  
**Rol tuyo:** implementador (no arquitecto)  
**Arquitecto / auditor:** Grok — ver [ROLES.md](./ROLES.md)  
**Plan de trabajo:** [WORK_PLAN.md](./WORK_PLAN.md) ← elige el primer WP en estado `READY`

---

## 1. En una frase

Motor de **reglas** locales que **planifica → aplica → deshace** movimientos de archivos.  
La percepción (heurísticas, CLIP, OCR, VLM) **solo rellena `features`**.  
Nunca mueves archivos fuera de `executor.py`.

---

## 2. Arranque en 5 minutos

```bash
cd "/home/carlos/file wizard"
source .venv/bin/activate
pip install -e ".[dev,ui]"
pytest -q
# Baseline esperado: ≥ 224 passed, version 0.11.0
python -c "from filewizard import __version__; print(__version__)"
```

Layout:

```text
src/filewizard/           # código
  perception/             # cascade, cache, zeroshot, HTTP
  ui/                     # PySide6 (no lógica de FS)
  plugins/                # heuristics legacy
tests/                    # pytest (sin display para core)
docs/WORK_PLAN.md         # ← tu cola de trabajo
AGENTS.md                 # arquitectura y contratos
```

---

## 3. Flujo de trabajo (cada sesión)

1. Abre **WORK_PLAN.md** → toma el WP con status `READY` de **menor número** (salvo que el humano diga otro).
2. Lee la sección del WP: objetivo, archivos, I/O, tests, fuera de scope.
3. Implementa **solo ese WP**.
4. `pytest -q` verde.
5. Resume en el formato de handoff de [ROLES.md](./ROLES.md) §5.
6. **No** marques el WP `DONE` en el plan si el arquitecto no ha auditado (márcalo `IN_REVIEW`).

Si el WP dice `BLOCKED` o `NEEDS_ADR`: no inventes; escribe pregunta en `BACKLOG_NOTES.md` o en el mensaje de handoff.

---

## 4. Invariantes (fallar = rechazo en audit)

| # | Regla |
|---|--------|
| I1 | Dry-run por defecto en CLI; mutación solo con `--execute` / apply UI. |
| I2 | Percepción no mueve archivos. |
| I3 | UI no contiene lógica de move/rename (solo llama core). |
| I4 | Imports del core no requieren torch / PySide6 / pytesseract. |
| I5 | Nuevas condiciones → campo en `Condition` + check en `engine` + `ConditionCheck`. |
| I6 | Undo no inventa datos ni pisa archivos inesperados (ver tests journal). |
| I7 | Perfil `recommended` = **cascada**, no OCR+VLM en todos los archivos. |
| I8 | Pesos de modelos no van en el paquete Python. |

Detalle: **AGENTS.md §3.4** y **ROBUSTNESS.md**.

---

## 5. Dónde tocar qué

| Quieres… | Módulo |
|----------|--------|
| Nueva condición de regla | `models.py` + `engine.py` + test_engine |
| Mover/renombrar | solo `executor.py` |
| Journal / undo | `journal.py` + tests journal |
| Scan | `scanner.py` |
| Pipeline compartido | `pipeline.py` |
| Cascada / stages | `perception/cascade.py` |
| Nuevo backend OCR/vision | `perception/extractors.py` + factory + config |
| Zero-shot | `perception/zeroshot.py` |
| Cache | `perception/cache.py` |
| Snapshot journal | `perception/snapshot.py` |
| Cola manual | `review_queue.py` + `ui/review_dialog.py` |
| CLI | `cli.py` |
| GUI | `ui/*` (strings en español) |
| MCP (futuro) | paquete nuevo bajo `src/filewizard/mcp/` (ver WP 0.7) |

---

## 6. Estado del producto (no reimplementar)

Ya existe y está testeado:

- Cascade stages 0–3 (`CascadeExtractor`)
- Zero-shot opcional (`[zeroshot]`)
- Condiciones `cascade_*`
- Review queue + UI
- Cache por hash + config fingerprint
- Journal `operations.perception`
- Presets, pipeline CLI=UI, cancel/progress

---

## 7. Estilo

- Inglés en código; español en UI.
- Pydantic v2 models; early returns; sin magic silent defaults.
- Tests en `tests/test_*.py`; preferir unitarios sin red real (mock HTTP).
- Version bump **solo** si el WP lo pide (normalmente al cerrar hito 0.5 / 0.6 / 0.7).

---

## 8. Primer WP recomendado

Abre [WORK_PLAN.md](./WORK_PLAN.md) y empieza por el primer WP `READY`.

- Hitos **0.5–0.11** cerrados; baseline `0.11.0`.
- **No hay WP READY.** No inventes 0.12 ni features de ROADMAP.
- Auditoría 0.9: [AUDIT_0.9.md](./AUDIT_0.9.md) (remediada).
