# FileWizard — Carta de robustez

Política del proyecto para **no-happy-path**, Unicode y manejo de recursos.
Implementada a partir de V0.3.

## Aislamiento y errores

| ID | Regla |
|----|--------|
| **R1** | Un archivo malo no mata el lote. `collect_facts` / plan / execute por archivo en try/except; status `error` + mensaje. |
| **R2** | Nada de excepciones silenciosas. Errores de lote → diálogo/`ClickException`; por archivo → status + journal/log. |
| **R3** | Fail-fast en configuración. YAML malformado, regex inválida o acción vacía fallan **al cargar** la regla. |
| **R4** | Journal como fuente de verdad. Ciclo `pending → done/failed/skipped`. Al arrancar la UI, `pending` se ofrece marcar como `interrupted`. |
| **R5** | Undo es una operación. Se journalea, puede fallar; archivo ausente → `missing`, no crash. |
| **R6** | `replace` es peligroso por diseño. No borra directorios; default `append`; UI no lo sugiere como primera opción. |

## Unicode / i18n

| ID | Regla |
|----|--------|
| **R7** | Rutas siempre como `Path`. Nombres preservados tal cual (sin transliterar). |
| **R8** | Matching con `casefold()` + normalización **NFC**. Renombre **nunca** reescribe el nombre original. |
| **R9** | Surrogates/bytes inválidos: UI con `safe_display` (`errors=replace`); operaciones usan `Path` real. |
| **R10** | YAML y texto de reglas se leen UTF-8 explícito. |

## Recursos

| ID | Regla |
|----|--------|
| **R11** | Imágenes en contexto acotado. Thumbnails vía `QImageReader` escalado / PIL thumbnail 48×48. No decodificar full-size para preview. |
| **R12** | Una conexión SQLite por hilo (`Journal` por worker), `timeout=10`, `close()` al terminar. |
| **R13** | Workers: `deleteLater()`, UI deshabilitada, cierre de ventana bloqueado durante operación. |
| **R14** | Symlinks no se siguen; fifos/sockets/devices ignorados. |
| **R15** | Idempotencia: `source == destination → noop`; double-undo no repite (`undone` fuera del set). |

## Principio

> La percepción aporta evidencia; las reglas deciden; el journal deshace.
