# Definition of Done — FileWizard

Usado por el **implementador** (auto-check) y el **arquitecto** (audit).

---

## A. Por work package (WP)

Un WP se puede marcar `DONE` solo si:

| # | Criterio |
|---|----------|
| 1 | Objetivo del WP cumplido (I/O del plan) |
| 2 | Fuera de scope **no** implementado por accidente |
| 3 | `pytest -q` verde en el entorno del repo |
| 4 | Tests nuevos o extendidos listados en el WP (si el WP los exige) |
| 5 | No se rompen invariantes I1–I8 de IMPLEMENTER_BRIEF |
| 6 | Sin imports pesados (torch, PySide6) en módulos core no-UI |
| 7 | UI (si aplica): strings en español, sin lógica FS en `ui/` |
| 8 | Docs del WP: si el WP pide actualizar USER_MANUAL / example yaml, hecho |
| 9 | Handoff rellenado (ROLES §5) |
| 10 | Architect audit: **APPROVE** |

---

## B. Por release de versión (0.5 / 0.6 / 0.7)

Además del DoD de todos los WPs del hito:

| # | Criterio |
|---|----------|
| 1 | Versión single-source: `pyproject.toml dynamic.attr == filewizard.__version__` (test `test_version_single_source`) |
| 2 | README + ROADMAP + AGENTS §2 actualizados |
| 3 | USER_MANUAL tocado si hay UX/CLI visible |
| 4 | Suite completa verde |
| 5 | Sin secretos, sin pesos de modelos en el tree |
| 6 | Humano confirma smoke opcional (UI / llama-server) |

---

## C. Checklist de auditoría rápida (arquitecto)

```text
[ ] ¿El diff respeta “percepción = evidencia”?
[ ] ¿Hay ConditionalCheck / journal donde toca?
[ ] ¿Tests cubren happy + un edge del WP?
[ ] ¿Hay dependencia nueva injustificada?
[ ] ¿Se expandió el scope?
[ ] ¿Migración de schema SQLite es aditiva (ALTER) y compatible?
[ ] ¿Config Pydantic tiene defaults seguros?
```

Verdict: `APPROVE` | `REQUEST_CHANGES` | `REDESIGN`
