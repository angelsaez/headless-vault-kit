# Registro de cambios

Bitácora del repositorio: una entrada por cambio, la más reciente arriba.
Formato: `## AAAA-MM-DD — título`, con qué cambió y por qué.


## 2026-08-15 — Finales de línea forzados a LF

- `.gitattributes` (nuevo): `* text=auto eol=lf` y binarios marcados como tales.
- Motivo: el destino es Linux y en Windows `core.autocrlf` estaba convirtiendo a CRLF al
  hacer checkout. Con vaults sintéticos de por medio, un final de línea cambiado altera
  el parsing y rompe la comparación de un rebuild determinista.

## 2026-08-15 — .gitignore y regla de bitácora

- `.gitignore`: secretos, ajustes locales de Claude Code, artefactos SQLite derivados,
  dependencias de Node/Python y estado de los vaults de prueba.
- `CLAUDE.md`: la verificación mínima incluye añadir entrada en este registro.
- Nota: entrada añadida a posteriori, al crear este archivo.
