# Plan de acción — Percepción pluggable (GLM-OCR + Qwen3-VL-2B)

**Estado:** plan aprobado de producto (sin implementación aún en este doc)  
**Principio:** la percepción aporta evidencia · las reglas deciden · el journal deshace  
**Decisión de defaults:**

| Rol | Default recomendado | Runtime |
|-----|---------------------|---------|
| OCR de calidad | **ggml-org/GLM-OCR-GGUF** (Q8_0) | `llama-server` |
| Visión semántica | **Qwen3-VL-2B-Instruct** (GGUF Q4/Q5 o HF) | `llama-server` / compatible OpenAI |
| OCR barato | Tesseract | sistema |
| Sin modelos | Heurísticas | core |

El usuario **puede cambiar** el modelo (u host) de cada rol si su hardware lo permite. La app **no** empaqueta pesos en el core.

---

## 1. Objetivos

1. Un diseño de **proveedores** (OCR / visión) intercambiables.
2. Defaults de producto: **GLM-OCR** + **Qwen3-VL-2B**.
3. Configuración por usuario/hardware: otro GGUF, NPU Nexa, 4B, solo Tesseract, o labels vía MCP.
4. Contrato de evidencia **estable** para el motor de reglas (sin reescribir N3/N4).
5. No degradar Lite: sin GPU y sin `llama-server`, todo sigue funcionando.

### No-objetivos (esta fase)

- Empaquetar GGUF en el wheel de FileWizard  
- Entrenar o fine-tunear modelos  
- Que el VLM decida `move_to` sin reglas  
- Daemon o MCP (siguen en 0.6 / 0.7; el diseño de providers los anticipa)

---

## 2. Arquitectura (núcleo N2)

```text
                    collect_facts(path, extractors=[...])
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
   ImageHeuristics            OcrProvider              VisionProvider
   (siempre en plan)          .extract(path)           .extract(path)
         │                         │                         │
         │                    features["ocr"]          features["vision"]
         │                    { text, provider,        { label: score, ...
         │                      model, error? }          provider, model }
         └─────────────────────────┼─────────────────────────┘
                                   ▼
                            Engine / Condition
                     ocr_contains_* · vision_label_gt
```

### Contrato de evidencia (congelado)

```json
{
  "ocr": {
    "text": "string",
    "provider": "tesseract|llama_http|none",
    "model": "optional-id",
    "error": "optional"
  },
  "vision": {
    "screenshot": 0.91,
    "document": 0.12,
    "photo": 0.05,
    "scan": 0.02,
    "invoice": 0.01,
    "provider": "llama_http|none",
    "model": "optional-id",
    "raw": "optional free text if parse failed"
  }
}
```

- Labels de visión: **conjunto canónico** documentado (extensible con prefijo `custom.*` o lista en config).
- Parseo JSON fallido → `error` / scores vacíos; **no** tumba el lote (R1).

### Proveedores (implementaciones)

| ID | Tipo | Default | Notas |
|----|------|---------|--------|
| `none` | — | off | |
| `tesseract` | OCR | OCR “barato” | Ya existe |
| `llama_http` | OCR y/o vision | **GLM-OCR** / **Qwen3-VL-2B** | OpenAI-compatible `POST /v1/chat/completions` + image |
| `nexa` *(futuro)* | vision | no | Snapdragon; opcional |
| `mcp_agent` *(futuro)* | ocr/vision | no | Labels inyectados por agente |

**Un solo transporte HTTP** sirve para cambiar de modelo: solo cambian `base_url`, `model` id y el **prompt template** (OCR vs labels JSON).

```text
~/.config/filewizard/perception.yaml   # o state_dir/config
```

Ejemplo:

```yaml
version: 1

heuristics: true

ocr:
  provider: llama_http          # none | tesseract | llama_http
  # Si llama_http:
  base_url: "http://127.0.0.1:8080/v1"
  model: "GLM-OCR-Q8_0"         # lo que exponga llama-server
  # Alternativas documentadas:
  # model: "LightOnOCR-..." 
  timeout_s: 120
  max_image_edge: 1600          # R11: no mandar 40MP
  temperature: 0.0

vision:
  provider: llama_http          # none | llama_http
  base_url: "http://127.0.0.1:8081/v1"   # segundo server o mismo si un solo modelo
  model: "Qwen3-VL-2B-Instruct-Q4_K_M"
  labels:
    - screenshot
    - document
    - photo
    - scan
    - invoice
    - social
  timeout_s: 120
  max_image_edge: 1280
  temperature: 0.0

# Perfiles de hardware (presets de config, no de reglas)
profiles:
  lite:
    ocr: { provider: tesseract }
    vision: { provider: none }
  recommended:                  # ★ default documentado
    ocr: { provider: llama_http, model: "GLM-OCR-Q8_0", base_url: "http://127.0.0.1:8080/v1" }
    vision: { provider: llama_http, model: "Qwen3-VL-2B-...", base_url: "http://127.0.0.1:8081/v1" }
  vision_only_strong:
    ocr: { provider: none }     # Qwen puede rellenar text en el mismo call si se pide
    vision: { provider: llama_http, model: "Qwen3-VL-4B-..." }
  agent:
    ocr: { provider: none }
    vision: { provider: none }  # evidencia vía MCP más adelante
```

Cambiar de modelo = editar `model` + `base_url` (o elegir perfil en UI). **No** recompilar FileWizard.

---

## 3. Runtime del usuario (defaults recomendados)

### OCR — GLM-OCR

```bash
# Terminal 1
llama-server -hf ggml-org/GLM-OCR-GGUF:Q8_0 --port 8080
# (mmproj según docs del modelo si aplica)
```

### Visión — Qwen3-VL-2B

```bash
# Terminal 2 (puerto distinto si ambos a la vez)
llama-server -hf <repo-gguf-qwen3-vl-2b> --port 8081
```

Documentar en README el par exacto de flags/mmproj cuando se implemente (smoke test en hardware real).

### Hardware guía

| RAM/VRAM | Perfil sugerido |
|----------|-----------------|
| Solo CPU, &lt;16 GB RAM | `lite` (Tesseract + heurísticas) |
| 8 GB VRAM / Mac 16 GB | `recommended`: GLM-OCR Q8 + Qwen3-VL-2B Q4 |
| 12+ GB VRAM | Qwen3-VL-4B en vision; OCR GLM o el mismo VLM |
| Snapdragon NPU | `vision.provider` experimental Nexa (doc aparte) |
| Agente con visión | `agent` + MCP (0.7) |

**Dos servidores** (8080 OCR + 8081 vision) es la config “recommended” más clara.  
**Un solo servidor** con un solo VLM (p. ej. solo Qwen) es válido: OCR y vision apuntan al mismo `base_url` con prompts distintos (menos óptimo en calidad OCR que GLM-OCR).

---

## 4. Integración en el código existente

### Módulos nuevos (propuestos)

```text
src/filewizard/
  perception/
    __init__.py
    config.py          # load perception.yaml + profiles
    protocol.py        # OcrBackend, VisionBackend protocols
    prompts.py         # plantillas OCR / JSON labels
    http_openai.py     # cliente chat.completions + image
    tesseract.py       # mover desde plugins/ocr.py
    factory.py         # build_extractors(config) → list[FeatureExtractor]
  plugins/
    heuristics.py      # sin cambio de rol
    vision.py          # de stub a delegación o deprecar
```

`pipeline.default_extractors()` pasa a:

```python
def default_extractors(*, perception_config=None, ocr_flag=False) -> list:
    return factory.build_extractors(perception_config, force_ocr=ocr_flag)
```

### CLI

```bash
filewizard perception status          # ¿responde 8080/8081? modelos configurados
filewizard perception test IMAGE      # imprime ocr/vision de un archivo
filewizard run --source DIR --preset P --ocr   # usa config OCR
filewizard run ... --vision                    # activa vision provider
```

### UI (mínimo viable)

- Ajustes → Percepción:
  - Perfil: Lite | Recomendado | Personalizado  
  - Estado: verde/rojo por endpoint  
  - Campos: URL OCR, modelo OCR, URL visión, modelo visión  
- Wizard: checkboxes “OCR” / “Visión” (respetan config)  
- Errores de modelo: en Motivo / status, no crash (R1–R2)

### Reglas / presets

- Ampliar `rules_sharp` o preset `images-cascade-ml` con `vision_label_gt` **opcional** (si no hay vision, esas reglas no matchean; las de nombre/heurística sí).
- No hacer las reglas ML el único camino: mantener cascada determinista como fallback.

---

## 5. Plan de acciones por fases

### Fase A — Contrato y config (núcleo N2 diseño)  
**Versión sugerida: 0.4.0-alpha / 0.4.0**

| # | Acción | Done when |
|---|--------|-----------|
| A1 | Definir `perception.yaml` schema + profiles `lite` / `recommended` | Validación Pydantic + tests |
| A2 | Protocolos `OcrBackend` / `VisionBackend` + forma canónica de features | Doc + unit tests de parseo |
| A3 | `prompts.py`: OCR text-only + vision JSON labels | Tests con fixtures de respuesta mock |
| A4 | `http_openai.py` con timeout, resize imagen, errores explícitos | Tests mock HTTP |
| A5 | `factory.build_extractors` + cablear `pipeline` | CLI dry-run sin server no rompe |

**No requiere** bajar GGUF en CI: todo mockeado.

---

### Fase B — Defaults GLM-OCR + Qwen3-VL-2B  
**0.4.1**

| # | Acción | Done when |
|---|--------|-----------|
| B1 | Doc: comandos `llama-server` exactos para ambos defaults | README + USER_MANUAL |
| B2 | `filewizard perception status/test` | Humano puede validar en 2 min |
| B3 | Integración real OCR con GLM-OCR (smoke manual + script) | Texto en facturas/capturas |
| B4 | Integración real vision con Qwen3-VL-2B (JSON labels) | Scores en `vision.*` usables en reglas |
| B5 | Preset ejemplo `images-cascade-ml.yaml` (heurística + vision opcional) | Dry-run documentado |

---

### Fase C — UX de cambio de modelo  
**0.4.2**

| # | Acción | Done when |
|---|--------|-----------|
| C1 | UI Ajustes: editar URLs/modelos + perfiles | Usuario cambia a 4B sin código |
| C2 | CLI flags o env: `FILEWIZARD_OCR_MODEL`, `FILEWIZARD_VISION_URL` | Scripts / agentes |
| C3 | Lista “modelos conocidos” en doc (GLM-OCR, Qwen2/3-VL-2B/4B, LightOnOCR, LFM2.5-VL) | No hardcodear solo 2 en código; sí en defaults |
| C4 | Advertencias de latencia + límite de archivos con ML | No escanear 10k con vision sin `--limit` |

---

### Fase D — Endurecimiento y escala

| # | Acción | Status |
|---|--------|--------|
| D1 | Progreso + cancel en workers | ✅ 0.4.0 |
| D2 | Cache de features por hash de archivo | ✅ 0.4.4 (`perception/cache.py`) |
| D3 | Cola / semáforo: 1 inferencia a la vez por provider | ⏳ (calls sequential; no pool) |
| D4 | Tests de caos: server caído, timeout, imagen corrupta | Parcial (probe + extractor errors) |

**También (cascada, fuera del plan original de providers):**  
0.4.2 cascade · 0.4.3 zeroshot + review queue · 0.4.4 journal snapshot.  
Ver `PLAN_CASCADE.md`.

---

### Fase E — Después (fuera de este plan de modelos)

| Versión | Qué |
|---------|-----|
| 0.6 | Watcher + presets |
| 0.7 | MCP: mismos tools; `apply_agent_labels` reutiliza el contrato `vision`/`ocr` |

---

## 6. Orden de implementación recomendado (secuencia)

```text
HECHO (hasta 0.4.4)
  1. 0.4.0  Providers + progress/cancel
  2. 0.4.1  UI Ajustes modelos
  3. 0.4.2  Cascada barato→OCR→VLM
  4. 0.4.3  Zero-shot + cola revisión + cascade_* rules
  5. 0.4.4  Cache hash + journal perception snapshot

SIGUIENTE
  6. 0.5   Backends extra (mismo contrato)
  7. 0.6   Watcher / automation
  8. 0.7   MCP reutiliza el mismo contrato features
```

**Por qué no empaquetar GGUF en el repo:**  
el valor está en el **conector + contrato**; los pesos los elige el usuario.

---

## 7. Criterios de done (config “recommended”)

**Estado código (0.4.4):** factory, cascade, settings UI, cache, journal snapshot y tests (80+) están. Validación real con GGUF sigue siendo smoke manual del usuario.

- [x] Sin `llama-server`: perfil lite / cascade stage0 funciona (regresión tests).  
- [ ] Con solo GLM-OCR: `ocr_contains_*` mejora en documentos.  
- [ ] Con solo Qwen3-VL-2B: `vision_label_gt.screenshot` / `document` discriminan mejor que solo regex.  
- [ ] Usuario cambia `model` a Qwen3-VL-4B (u otro GGUF en el mismo API) y plan sigue igual.  
- [ ] Server caído → archivos con error de provider, lote continúa.  
- [ ] Documentación de perfiles hardware en USER_MANUAL / ROADMAP.

---

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|--------|------------|
| Dos puertos / dos procesos confunden | Perfil `recommended` + script `scripts/start-perception.sh` |
| Qwen no devuelve JSON válido | Retry con prompt estricto; fallback `raw` + sin scores |
| Latencia | `--limit`, solo imágenes, cache, vision off por defecto en run masivo |
| Licencias de pesos | Documentar licencia de cada GGUF; no redistribuir en el wheel |
| Fragmentación de backends | Un solo cliente HTTP OpenAI-compatible; Nexa/MCP como adapters del mismo Protocol |

---

## 9. Resumen ejecutivo

| Pregunta | Respuesta |
|----------|-----------|
| ¿Defaults de producto? | **GLM-OCR** (OCR) + **Qwen3-VL-2B** (visión) |
| ¿Otros modelos? | Sí: mismo `provider: llama_http`, otro `model` / `base_url` / perfil |
| ¿Core? | Sin pesos; solo extractors + config |
| ¿Siguiente código? | **0.3.4 progreso/cancel** → **0.4.0 factory de providers + mocks** → **0.4.1 defaults reales** |

La app queda “suficiente” con esos dos modelos en la práctica, y **preparada para hardware mejor** (4B, NPU) o **sin modelos** (heurísticas + MCP), sin reescribir el motor de reglas.
