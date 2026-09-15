# Cascada de percepción — "Barato primero, caro solo si hace falta"

**Estado:** implementado en producto **0.4.2–0.4.4** (C0–C3 + cache C4.3)  
**Principio:** la percepción aporta evidencia · las reglas deciden · el journal deshace  
**Complementa:** [PLAN_PERCEPTION_PROVIDERS.md](./PLAN_PERCEPTION_PROVIDERS.md) (proveedores HTTP pluggables)  
**Manual usuario:** [USER_MANUAL.md](./USER_MANUAL.md) §6

---

## 1. Por qué una cascada

Si se llama un VLM (Qwen) en **cada** archivo:

- Latencia 1–3 s × N archivos → UX inaceptable  
- GPU/RAM saturada  
- Coste de “modelo grande” sin necesidad  

La cascada resuelve el **90 %+** en etapas baratas y solo escala a OCR/VLM cuando la confianza es media o baja.

```text
[1000 archivos]
     │
     ▼
[Etapa 0: Heurísticas] ──── casi gratis (nombre, EXIF, paleta) ──► features
     │
     ▼
[Etapa 1: Zero-shot] ──── ~850 resueltos (ms) ──► vision scores + category
     │ (~150 ambiguos)
     ▼
[Etapa 2: OCR/Caption] ── ~120 validados ──► ocr.text + confirm/reject
     │ (~30 difíciles)
     ▼
[Etapa 3: VLM JSON] ──── ~25 resueltos ──► category + confidence + slug
     │ (~5 sin consenso)
     ▼
[Cola revisión manual]  ◄── usuario decide
```

**Invariante:** ninguna etapa mueve archivos. Solo rellenan `features`. El **Rule engine** (N3) + **Executor/Journal** (N4) deciden y aplican.

---

## 2. Mapa a núcleos FileWizard

| Etapa | Rol | Modelo default | Runtime | Provider id |
|-------|-----|----------------|---------|-------------|
| **0** | Señal determinista | (core) | local | `heuristics` |
| **1** | Clasificación zero-shot | SigLIP / CLIP | local (transformers/onnx) o HTTP | `zeroshot` |
| **2** | Evidencia dura (OCR/caption) | **GLM-OCR** (OCR) · Florence-2 opcional (caption) | llama-server / HF | `ocr` / `caption` |
| **3** | Desempate instruct | **Qwen3-VL-2B** (o 3B/4B) | llama-server | `vision` (VLM) |
| Manual | Usuario | — | UI | review queue |

**Defaults de producto (recomendados):**

| Etapa | Elección FileWizard |
|-------|---------------------|
| 1 | CLIP (default) / SigLIP vía `filewizard[zeroshot]` (0.4.3+); opcional |
| 2 | **GLM-OCR-GGUF** (ya en plan providers) |
| 3 | **Qwen3-VL-2B** (ya en plan providers) |

Florence-2 es una **alternativa** a etapa 2 (caption + OCR en un modelo). No es obligatorio si GLM-OCR + heurísticas bastan; se documenta como backend intercambiable.

---

## 3. Contrato de evidencia de cascada

Todo va en `features` (auditable, no solo el label final):

```json
{
  "heuristics": { "...existing..." },
  "cascade": {
    "stage_used": 1,
    "category": "screenshot",
    "confidence": 0.91,
    "status": "confirmed",
    "stages": {
      "0": { "patterns": ["screenshot"], "date_source": "filename" },
      "1": {
        "provider": "siglip",
        "top_label": "captura_pantalla",
        "top_score": 0.91,
        "scores": { "captura_pantalla": 0.91, "foto_paisaje": 0.05 }
      },
      "2": null,
      "3": null
    }
  },
  "ocr": { "text": "...", "provider": "llama_http", "model": "GLM-OCR-Q8_0" },
  "vision": {
    "screenshot": 0.91,
    "document": 0.05,
    "provider": "cascade",
    "model": "siglip"
  }
}
```

### Umbrales (configurables en Ajustes)

| Clave | Default | Significado |
|-------|---------|-------------|
| `high_confidence` | 0.75 | Etapa 1 decide sola → no etapa 2/3 |
| `medium_confidence` | 0.50 | Etapa 1 ambigua → etapa 2 |
| `vlm_min_confidence` | 0.70 | Bajo esto tras VLM → cola manual |
| `stage2_keyword_min_hits` | 2 | Validación determinista OCR |

### Estados de decisión (cascada)

| status | Significado |
|--------|-------------|
| `confirmed` | Listo para reglas (alta confianza) |
| `probable` | Aceptable; reglas pueden pedir review si quieren |
| `rejected` | Hipótesis etapa 1 falsa; reintentar o etapa 3 |
| `unknown` | Sin consenso → cola manual |
| `error` | Fallo de provider (R1: no tumba el lote) |

---

## 4. Lógica por etapa (especificación)

### Etapa 0 — Heurísticas (ya en core)

- `filename_patterns`, EXIF, `unique_colors`, `date_taken`
- Puede **saltar** a categoría directa (ej. nombre `Screenshot_*` → `screenshot` con conf 0.95) **sin** SigLIP

### Etapa 1 — Zero-shot (SigLIP / CLIP)

```text
INPUT:  imagen + LABELS[]
OUTPUT: scores[label], top_label, top_score

if top_score >= high_confidence:
    stage_used = 1; status = confirmed; map → vision.*
elif top_score >= medium_confidence:
    stage_used = 1; status = probable; trigger stage 2 with hint
else:
    trigger stage 2 with hint=unknown
```

Labels default (es/en, configurables):

```text
factura, recibo, documento_escaneado, formulario,
captura_pantalla, foto_persona, foto_paisaje, foto_producto,
meme, grafico, diapositiva, interfaz_web, codigo
```

Mapeo a keys de reglas actuales: `captura_pantalla` → `vision.screenshot`, `factura` → `vision.invoice` / ocr path, etc.

### Etapa 2 — OCR / caption (GLM-OCR o Florence-2)

| Hint etapa 1 | Tarea | Validación |
|--------------|-------|------------|
| factura / recibo | OCR | keywords + regex fecha |
| documento | OCR (+ caption opcional) | densidad texto |
| captura | OCR + caption | UI cues, URLs |
| foto_* | caption | tags escena |
| meme | OCR + caption | texto superpuesto |

```text
if keyword_hits >= N and optional date_ok:
    status = confirmed
elif keyword_hits >= 1:
    status = probable
else:
    status = rejected → stage 3
```

**Default FileWizard etapa 2:** `llama_http` → **GLM-OCR** (solo texto). Caption Florence-2 = backend futuro `caption.provider`.

### Etapa 3 — VLM JSON estricto (Qwen3-VL-2B)

- `temperature: 0`, `max_new_tokens` acotado  
- Prompt JSON-only (category, confidence, reasoning, filename_slug, tags)  
- `safe_parse` + categoría ∈ allowlist  
- Fallo de parse → `unknown` + cola manual  

**Default:** mismo cliente HTTP que hoy, modelo **Qwen3-VL-2B**.

---

## 5. Integración con el motor de reglas (N3)

La cascada **no sustituye** YAML rules. Produce evidencia que las reglas consumen:

```yaml
# Ejemplo (0.4.3+) / preset cascade-aware
when:
  mime_prefixes: [image/]
  # category can map to vision_label_gt or new condition category_eq
  vision_label_gt:
    screenshot: 0.75
then:
  move_to: "~/Pictures/Screenshots/{year}/{month}"
```

Ampliaciones de `Condition` (**implementadas 0.4.3**):

| Campo | Uso | Status |
|-------|-----|--------|
| `cascade_category_any` | `["factura", "recibo"]` | ✅ |
| `cascade_status_any` | `["confirmed", "probable"]` | ✅ |
| `cascade_min_confidence` | float | ✅ |
| `cascade_stage_max` | int (solo archivos resueltos sin VLM, etc.) | ✅ 0.5.2 |

Category también se mapea a `features["vision"][label]` para reglas `vision_label_gt` legacy.

---

## 6. Journal: evidencia completa (N4)

Hoy el journal guarda move/undo. **Extensión (fase 2 del cascade):**

**Opción B implementada (0.4.4):** columna `operations.perception` (JSON compacto vía `perception_snapshot`).

```json
{
  "cascade": {
    "stage_used": 2,
    "category": "factura",
    "confidence": 0.88,
    "status": "confirmed",
    "stages": {"2": {"provider": "llama_http", "text_len": 120}}
  },
  "ocr": {"provider": "cascade", "text_len": 120, "text_preview": "Factura…"}
}
```

Cola de revisión (0.4.3): `review_queue.json` + UI; se rellena en preview (`on_facts`).  
Feedback “usar para retune umbral”: pendiente.

---

## 7. Pantalla de Ajustes (contenido concreto)

El diálogo actual **Ajustes…** (percepción OCR/visión) se **amplía** en secciones. No es un explorador de archivos.

### Sección 1 — Modelos y estado (descargas / endpoints)

| Rol | Default | Estado | Acción |
|-----|---------|--------|--------|
| Etapa 1 Zero-shot | SigLIP (local) | Descargado / Falta | [Estado] [Doc] |
| Etapa 2 OCR | GLM-OCR @ :8080 | OK / DOWN | URL + modelo + Comprobar |
| Etapa 3 VLM | Qwen3-VL-2B @ :8081 | OK / DOWN | URL + modelo + Comprobar |

Pie: *“Los modelos se ejecutan en local (o en el endpoint que configures). FileWizard no sube tus archivos a la nube.”*

Nota: la app **no** embebe pesos; “Descargar” puede abrir docs o lanzar `llama-server -hf …` / script `start-perception.sh`.

### Sección 2 — Umbrales de cascada

```text
Confianza alta (decide en etapa 1)     [0.75]
Confianza media (pasa a etapa 2)       [0.50]
Confianza mínima VLM (si no → manual)  [0.70]
Máx. archivos con etapa 2/3 por lote   [50]   # protege latencia
```

### Sección 3 — Categorías y destinos (biblioteca de labels)

Tabla editable (persistir en `perception.yaml` o `categories.yaml`):

| category | slug | carpeta destino (plantilla) | keywords etapa 2 |
|----------|------|----------------------------|------------------|
| factura | invoices | ~/Documents/Invoices/{year} | total, iva, factura, invoice |
| captura_pantalla | screenshots | ~/Pictures/Screenshots/{year}/{month} | (heurística nombre) |
| unknown | review | ~/FileWizard/Review | — |

Esto alimenta **presets** generados o plantillas de RuleSet (no reescribe el engine a “hardcode de carpetas” sin reglas).

### Sección 4 — Renombrado

Plantilla con variables ya existentes + futuras:

```text
{date}_{category}_{slug}_{hash6}
```

Opciones: minúsculas, guiones, sin acentos, hash solo en colisión — la mayoría ya existen en `template.py` / `on_collision`.

### Sección 5 — Rendimiento y privacidad

```text
Dispositivo: CPU | GPU (vía server externo) | NPU (backend opcional)
Batch size inferencia: [4]
Workers: [1]  # default 1: un request a la vez al server (R12)
☑ Cache embeddings / OCR por hash de archivo
☐ Telemetría (siempre off por defecto)
```

### Sección 6 — Proveedores (ya implementado 0.4.x)

Profile lite / recommended / ocr_only / vision_only + URLs/modelos editables.

---

## 8. Flujo de código (orquestador)

```text
CascadeExtractor.extract(path):
    features = {}
    # Stage 0
    features += heuristics(path)
    if hard_rule_from_heuristics:  # e.g. filename screenshot
        return finalize(stage=0, ...)

    # Stage 1 (if enabled)
    s1 = zeroshot(path, labels)
    features.cascade.stages[1] = s1
    if s1.top_score >= high:
        return finalize(stage=1, confirmed)

    # Stage 2 (if enabled and needed)
    s2 = ocr_or_caption(path, hint=s1.top_label)
    features.ocr = ...
    if validate(s2, hint): return finalize(stage=2, confirmed)
    
    # Stage 3 (if enabled and needed)
    s3 = vlm_json(path, categories)
    if parse_ok and s3.confidence >= vlm_min:
        return finalize(stage=3, confirmed)
    return finalize(stage=3, unknown)  # review queue
```

`CascadeExtractor` implementa `FeatureExtractor` y se inserta en `build_extractors` **en lugar de** lanzar OCR+VLM siempre en paralelo (como hoy en perfil recommended).

**Cambio de semántica 0.4 → cascade:**

| Antes (0.4.0 dual) | Cascada (0.4.2+) |
|--------------------|-------------------|
| recommended = OCR + vision en **todo** archivo | recommended = etapa 0→1→2→3 **solo si hace falta** |
| Coste alto en batch | Coste bajo en batch + cache (0.4.4) |

---

## 9. Plan de implementación (acciones)

### Fase C0 — Contrato (sin modelos pesados) — **DONE 0.4.2**

| # | Acción | Status |
|---|--------|--------|
| C0.1 | Schema `cascade` en config + umbrales en `perception.yaml` | ✅ |
| C0.2 | `CascadeResult` + map labels → vision.* | ✅ |
| C0.3 | `CascadeExtractor` etapa 0 + 2 + 3 | ✅ |
| C0.4 | Ajustes UI: umbrales + cascada | ✅ |
| C0.5 | Tests cascade / profiles | ✅ |

### Fase C1 — Etapa 2/3 con providers — **DONE 0.4.2**

| # | Acción | Status |
|---|--------|--------|
| C1.1 | Stage 2 = OCR solo si no confirmed | ✅ |
| C1.2 | Stage 3 = VLM si rejected/unknown/probable | ✅ |
| C1.3 | Perfil `recommended` = cascade mode | ✅ |
| C1.4 | Preset `images-cascade` determinista | ✅ (ML via conditions opcionales) |

### Fase C2 — Etapa 1 zero-shot — **DONE 0.4.3** (parcial C2.3)

| # | Acción | Status |
|---|--------|--------|
| C2.1 | Backend `zeroshot` (`filewizard[zeroshot]`) | ✅ CLIP vía transformers; SigLIP id configurable |
| C2.2 | No pesos en wheel; doc en README / perception.example | ✅ |
| C2.3 | Benchmark % resuelto stage 1 en carpeta real | ⏳ pendiente (manual) |

### Fase C3 — Cola manual + journal perception — **DONE 0.4.3–0.4.4**

| # | Acción | Status |
|---|--------|--------|
| C3.1 | UI cola: unknown / low confidence | ✅ `review_dialog` + enqueue en preview |
| C3.2 | Asignar categoría / dismiss | ✅ (sin “retune umbral” aún) |
| C3.3 | Snapshot perception en journal | ✅ `operations.perception` + `snapshot.py` |

### Fase C4 — Batch / RAM

| # | Acción | Status |
|---|--------|--------|
| C4.1 | Batch size etapa 1 (SigLIP) | ⏳ no |
| C4.2 | Semáforo 1-inflight etapa 2/3 | ⏳ no (server-side / sequential calls) |
| C4.3 | Cache por hash de archivo | ✅ **0.4.4** `perception/cache.py` |

Condiciones de reglas (`cascade_category_any`, `cascade_status_any`, `cascade_min_confidence`): ✅ 0.4.3

---

## 10. Respuesta a “¿batch o cola manual?”

| Tema | Estado |
|------|--------|
| Contrato cascada + orquestador (C0–C1) | **Hecho** |
| Cola de revisión manual (C3) | **Hecho** (retune umbrales = futuro) |
| Cache por hash (C4.3) | **Hecho** |
| Batch GPU etapa 1 (C4.1) | Opcional si hay volumen real |

---

## 11. Resumen

| Pregunta | Respuesta |
|----------|-----------|
| ¿Cascada tiene sentido? | **Sí** — implementada en 0.4.2+ |
| ¿Choca con GLM-OCR + Qwen? | **No** — son etapa 2 y 3; zero-shot es etapa 1 |
| ¿Choca con providers HTTP? | **No** — se llaman condicionalmente |
| ¿El VLM decide carpetas? | **No** — solo evidencia; reglas / presets deciden |
| ¿Estado producto? | **0.4.4**: cascade + zeroshot opcional + cola + cache + journal snapshot |
| ¿Siguiente? | **0.5** backends extra · **0.7** MCP · benchmark stage 1 opcional |

Privacidad: todo local o endpoint que el usuario configure; sin telemetría por defecto.
