# Auditoría de producto — FileWizard 0.7.0 → remediado en **0.8.0**

**Fecha auditoría:** 2026-08-13  
**Remediaciones shipped:** 0.8.0 (148 tests)  
**Auditor:** Grok (arquitecto)  
**Baseline original:** `0.7.0` · **144 tests**  
**Alcance:** core, percepción, MCP, CLI, UI/UX, docs. Sin smoke GGUF/GPU (humano).

> **Estado:** hallazgos P0/P1 de esta auditoría están **cerrados en 0.8.0**.  
> Ver [CHANGELOG.md](../CHANGELOG.md) y [RELEASE.md](./RELEASE.md).

---

## 1. Veredicto

El motor es **sólido** (reglas, journal, dry-run, cascada, watcher, MCP).  
El hueco grande no es “más backends”: es que **varias capacidades 0.4–0.7 no llegan al usuario de la GUI** y que **MCP plan/execute ignoran percepción**.

| Área | Salud | Nota |
|------|-------|------|
| Core (engine, executor, journal, scanner) | **Buena** | Contratos estables; undo seguro |
| Percepción / cascada | **Buena con bugs** | Early-stop OK; clasificación factura en stage 2 frágil |
| CLI / presets / watch | **Buena** | Watch no tiene UI |
| MCP | **Buena con hueco P0** | Confirm gate OK; plan/execute `extractors=()` |
| GUI / UX | **Débil vs producto** | Home denso; cola/journal/watch/ajustes incompletos |
| Tests | **Buena** | 144 unitarios; **cero** tests GUI |
| Docs | **Buena** | Manual 0.7; handover al día |

**Recomendación de hito 0.8:** *calidad + UX de lo ya shipped*, no NPU/4B.

---

## 2. Fortalezas (no reabrir)

- Separación percepción / reglas / journal (ADR-0001).
- Cascada barato-primero (ADR-0002); perfil `recommended`.
- Pipeline único CLI/UI/MCP.
- Journal + undo (size check, no overwrite).
- MCP 9 tools; execute/undo con `confirm is True`.
- Agent inject canónico (`normalize_agent_features`).
- Extra `[mcp]` / `[zeroshot]` sin contaminar el core (I4).

---

## 3. Hallazgos (priorizados)

### P0 — Correctitud / contrato

| ID | Hallazgo | Evidencia | Impacto |
|----|----------|-----------|---------|
| **F1** | `filewizard_plan` / `filewizard_execute` (MCP) llaman `plan_operations(..., extractors=())`. Las reglas `cascade_*` / OCR / vision **no matchean** salvo labels inyectados. | `mcp/tools.py` | Agente MCP no puede usar percepción local; 0.7 queda “a medias” |
| **F2** | Stage 2 invoice: `category="factura" if "factura" in hint or status` — `status` es string no vacío → **casi siempre `factura`** si pasa validación OCR. | `cascade.py` ~365 | Recibos/docs se etiquetan mal |
| **F3** | `only_paths` compara `Path` sin `.resolve()` sistemático. | `pipeline.py` + watch | Debounce puede no filtrar en paths no canónicos |

### P1 — UX de features ya shipped

| ID | Hallazgo | Impacto usuario |
|----|----------|-----------------|
| **F4** | Home: 7 intents + presets + historial en ~740px; **sin badge** de cola de revisión. | Cola invisible; “¿qué hago?” se diluye |
| **F5** | Intent `images-cascade-ml` **no está en la home** (solo combo presets). | El preset “ML” no se descubre |
| **F6** | Wizard de regla única **no expone** `cascade_*`, `filename_pattern_any`, negaciones. | GUI ≠ potencia YAML |
| **F7** | Checkboxes OCR/visión no explican relación con **Ajustes / cascada**. “Activar OCR” vs cascade stage 2 confunde. | Usuario no sabe si se llama GLM o Tesseract |
| **F8** | **Ajustes** 560×520, un solo scroll implícito: umbrales + URLs + cache + notes = recorte en portátiles. Catálogo 0.5.1 no está en UI. | Config difícil |
| **F9** | Historial **no muestra** `operations.perception` (stage, category). Preview tampoco. | “¿Por qué se clasificó así?” no se ve |
| **F10** | Cola de revisión: sin thumbnail, sin badge, categoría asignada **no vuelve** a reglas ni a un segundo plan. | Cola es callejón sin salida |
| **F11** | **Watch no existe en GUI** (solo CLI). | Automatización 0.6 invisible para usuario de escritorio |
| **F12** | Review wizard: no hay indicador de “N en cola de revisión” tras preview. | Feedback incompleto |

### P2 — Pulido / deuda

| ID | Hallazgo |
|----|----------|
| **F13** | `ActiveWatch.interval_s` se guarda pero `watch run` es un tick. |
| **F14** | Flag CLI `watch once --once` redundante. |
| **F15** | `plugins/vision.py` sigue siendo stub; docs a veces hablan de “stub vision”. |
| **F16** | MCP plan no acepta `perception_profile` / `enable_ocr`. |
| **F17** | No hay “última carpeta origen” persistida. |
| **F18** | Sin atajos de teclado documentados (Enter/Esc en wizard sí; home no). |
| **F19** | Settings no usa `QScrollArea`. |
| **F20** | Cero tests PySide (`pytest-qt`). |
| **F21** | Semáforo HTTP 1-inflight (R12 / server) no implementado. |
| **F22** | Review queue JSON `load()` traga errores y deja cola vacía (silencioso). |

### P3 — Fuera de 0.8 (no planificar aún)

- Backends Nexa / 4B / NPU (catálogo ya documenta ids).
- Daemon systemd / tray / inotify.
- Packaging Flatpak.
- “Retune umbrales” desde la cola.
- Batch GPU zeroshot.

---

## 4. Recorrido UX (usuario no técnico)

```text
Home
  ¿Qué quieres hacer?  → 7 botones (2 de imágenes + facturas OCR)
  Presets combo        → incluye images-cascade-ml si refrescas
  Cola de revisión…    → vacío hasta un preview con cascada
  Ajustes…             → denso
  Historial            → lotes; sin “por qué”

Wizard (intent simple)
  Archivos → Condiciones (subset) → Acción → Revisar
  OCR/visión checkboxes opacos

Wizard (preset / cascada)
  Solo origen → Revisar  (bien)
  No se ve etapa usada ni category en la tabla

Cola
  Tabla texto; asignar categoría no cambia el siguiente plan
```

**Principio de producto roto en la GUI:** “la percepción aporta evidencia” — la evidencia **casi no se enseña**.

---

## 5. Mapa 0.8 (respuesta al hallazgo)

Hito **0.8 — “Lo shipped se entiende y se usa”**

1. MCP usa el mismo stack de percepción que CLI.  
2. Bug de categoría factura.  
3. Home + Ajustes usables.  
4. Journal/preview muestran snapshot.  
5. Cola con feedback visible.  
6. Watch mínimo en GUI.  
7. Release 0.8.0.

Detalle ejecutable: **[WORK_PLAN.md](./WORK_PLAN.md) § Hito 0.8**.

---

## 6. Criterio de éxito 0.8

Un usuario puede, sin YAML:

1. Elegir **Organizar imágenes (cascada ML)** desde home.  
2. Ver en preview **categoría / etapa / confianza**.  
3. Abrir cola con **badge** si hay unknowns.  
4. Desde Ajustes, **rellenar un modelo del catálogo** y ver umbrales sin recorte.  
5. Lanzar **un tick de watch** desde la GUI (dry-run).  
6. Un agente MCP con `filewizard_plan` **sí** obtiene matches `cascade_*` si hay `perception.yaml` recommended (aunque el server OCR esté down, al menos stage 0).
