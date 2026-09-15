# Auditoría sistemática — FileWizard 0.8.0 → hito 0.9

**Fecha:** 2026-08-13 (remediado 2026-09-04)  
**Baseline:** `0.8.0` · 148 tests (pre-0.9)  
**Shipped:** `0.9.0` · 163 tests  
**Alcance:** bugs, UI, pipeline, seguridad, no-happy-path, recursos, logs, excepciones.

## Veredicto

Motor **sólido**. Hito 0.9 = **endurecer runtime**, no más backends. **SHIPPED 0.9.0.**

## Hallazgos (resumen)

| ID | Sev | Estado |
|----|-----|--------|
| H1 Watch tick en hilo UI | P0 | **fixed 0.9** (`WatchTickWorker`) |
| H2 `continue` sin `finished += 1` | P0 | **fixed 0.9** |
| H3 ReviewQueue load silencioso | P1 | **fixed 0.9** (.bak + `load_error`) |
| H5 sleep bloquea cancel del loop | P1 | **fixed 0.9** (`interruptible_sleep`) |
| H4 HTTP 1-inflight | P1 | **fixed 0.9.4** (`_HTTP_LOCK` on POST only) |
| H6 closeEvent incompleto | P1 | **fixed 0.9.4** (watch + preview dialogs) |
| H8 MCP sin allowed_roots | P1 | **fixed 0.9.5** (opt-in jail; CLI/GUI intact) |
| H9 logs GUI | P1 | **fixed 0.9.4** (`state_dir/filewizard.log` 1MB×3) |
| H14 CLI pending silencioso | P2 | **fixed 0.9.5** (`warn_pending_journal`) |

Detalle y workplan: `docs/WORK_PLAN.md` hito 0.9 (WP-0.9.1–0.9.6 DONE).
