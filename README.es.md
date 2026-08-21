[English](README.md) | **Español**

# headless-vault-kit

> Kit de herramientas para operar vaults de Obsidian sin interfaz: índice, consultas y
> automatización agéntica en un servidor 24/7. El CLI se instala como **`hvk`**.

## El problema

Un Nexus (vault de Obsidian + agente de IA + automatizaciones) necesita vivir en una máquina
siempre encendida. En un VPS sin pantalla, Obsidian Headless sincroniza el vault, pero al no
correr la aplicación se pierde todo lo que esta calcula al abrirse: backlinks, consultas
Dataview, Bases, el CLI, los plugins. Resultado: notas sincronizadas, cerebro apagado.

## La solución

No emular Obsidian: **replicar sus datos**. Todo lo que la app deriva al arrancar es estado
reconstruible desde los propios archivos. Este proyecto lo reconstruye en el servidor:

- **Indexador**: parsea el vault a SQLite igual que hace el metadata cache de la app
  (frontmatter, tags, enlaces, backlinks, tareas, encabezados, texto completo), con
  actualización incremental al ritmo del sync.
- **CLI `hvk`**: búsquedas, backlinks, tareas y propiedades en milisegundos, para
  que el agente consulte sin gastar tokens leyendo archivos.
- **Consultas sin app**: Bases (`.base`) y un subconjunto de Dataview (DQL) ejecutados
  contra el índice, con vistas materializadas a Markdown visibles desde el móvil.
- **Vault como cola**: notas-orden con estado en frontmatter; un runner las ejecuta con
  Claude Code y el resultado se sincroniza de vuelta a todos tus dispositivos.
- **Harness**: permisos, hooks y auditoría con los medios nativos de Claude Code + git.

El criterio de alcance es un modelo de tres niveles: el comportamiento natural de la app se
replica exacto; los formatos oficiales de Obsidian (Bases, Canvas, plantillas) se soportan
completos; y los plugins de comunidad más usados entran solo si su estado vive en archivos
parseables — el resto, vía una interfaz de parsers extensible para que cualquiera aporte
el suyo. Nunca se ejecuta código de plugins ni se reproduce la interfaz.

## Estado

🚧 **Fase 2 en marcha.** El indexador de Nivel 0 funciona: parsea un vault a SQLite y responde
búsquedas, backlinks, enlaces, etiquetas, tareas, propiedades y huérfanos, con
reconstrucción determinista. Queda pendiente de
la fase el watcher de sistema de archivos, el re-escaneo nocturno de verificación y la skill
de Claude Code.

El plan completo, con fases y criterios de salida, está en
[`.plans/Plan-v2-headless-vault-kit.md`](.plans/Plan-v2-headless-vault-kit.md); las decisiones
que sostienen el diseño, en [`docs/adr/`](docs/adr/).

## Probarlo

Todavía no está publicado, así que se ejecuta desde un clon. Python 3.11 o superior, y nada más:

```bash
git clone https://github.com/angelsaez/headless-vault-kit
cd headless-vault-kit
uv venv && uv pip install -e ".[dev]"        # o python -m venv .venv && .venv/bin/pip install -e ".[dev]"

.venv/bin/hvk --vault /ruta/al/vault scan
.venv/bin/hvk --vault /ruta/al/vault backlinks "Una nota"
```

Dentro de un vault se puede omitir `--vault`: hvk sube por el árbol hasta encontrar `.obsidian/`.

| Comando | Qué responde |
|---|---|
| `hvk scan` / `hvk rebuild` | Indexa lo nuevo y lo cambiado, o reconstruye desde cero |
| `hvk search "texto tag:proyecto path:Areas"` | Búsqueda a texto completo, con filtros de etiqueta y ruta |
| `hvk backlinks "Nota"` | Qué enlaza aquí, por nombre de nota o por ruta |
| `hvk links [Nota] [--broken] [--ambiguous]` | Enlaces salientes, los rotos, o aquellos donde encajó más de un archivo |
| `hvk tags [--count] [--prefix casa]` | Todas las etiquetas y cuántos archivos las llevan; el prefijo incluye las anidadas |
| `hvk tasks [--pending] [--due-before 2026-09-01]` | Tareas del vault, por estado, vencimiento o ruta |
| `hvk props --where "estado=abierto"` | Archivos por propiedad; repite `--where` para combinar con AND, u omítelo para ver el catálogo de claves |
| `hvk orphans [--attachments]` | Archivos que nadie enlaza |
| `hvk info` | Qué contiene el índice ahora mismo |

Todos los comandos aceptan `--json` para salida legible por máquina.

Cuando la herramienta se publique, instalarla serán dos comandos y ningún `sudo`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install hvk
```

## Hoja de ruta

| Fase | Qué entrega | Estado |
|---|---|---|
| 0 | Base operativa en el VPS: Headless + Claude Code/Telegram + git, sobrevive a reinicios | Pendiente |
| 1 | Inventario del vault: qué plugins y usos reales hay que cubrir | Pendiente |
| 2 | Indexador Nivel 0 + CLI `hvk` | **En curso** |
| 3 | Bases, Canvas, plantillas y notas periódicas | Pendiente |
| 4 | Dataview (DQL) + vistas materializadas | Pendiente |
| 5 | Notas-orden: el vault como cola de trabajos | Pendiente |
| 6 | Seguridad, healthchecks, backups ensayados | Pendiente |
| 7 | MCP + parsers de comunidad + empaquetado | Futuro |

## ¿Qué necesito para usarlo?

Depende de la capa — el proyecto se usa por trozos, con dependencias distintas:

| Capa | Qué hace | Qué requiere |
|---|---|---|
| Índice + CLI (Fases 2–4) | Búsqueda, backlinks, tareas, propiedades, consultas Bases/DQL, vistas materializadas | **Solo tus archivos** (cualquier vault de Obsidian o carpeta de Markdown) + el runtime. Sin IA, sin app, sin suscripciones. No consume ni un token |
| Sincronización | Vault actualizado en el servidor | Obsidian Sync + Obsidian Headless, **o** git como transporte. El índice no distingue cómo llegan los archivos |
| Automatización inteligente (Fase 5) | Notas-orden que requieren criterio ("revisa", "resume", "detecta") | Un agente CLI. **Claude Code es la opción soportada de serie**; los formatos (YAML, Markdown, SQLite) son neutrales y cambiar de agente es tocar una línea del runner. Las órdenes deterministas (regenerar vistas, crear la diaria) no necesitan agente |
| Acceso 24/7 por chat | Hablar con tu Nexus desde el móvil | Claude Code + plugin de Telegram (o equivalente) |

Obsidian como aplicación solo hace falta donde siempre: en tus dispositivos, para leer
y escribir como humano.

## Requisitos del servidor de referencia

- VPS Linux (probado sobre 2 núcleos / 12 GB — sobra).
- Git.

## Estructura del repositorio

```text
.plans/     Planes de implementación (fuente de verdad del alcance)
docs/adr/   Decisiones de arquitectura (el «por qué» del diseño)
docs/       CHANGELOG.md — bitácora del repositorio
CLAUDE.md   Guía para el agente que desarrolla y opera este repo
README.md   Versión en inglés (por defecto) · README.es.md este archivo
```

El resto de carpetas (`src/hvk/`, `tests/`, `test-vaults/`, `runner/`, `deploy/`) irán
apareciendo a medida que sus fases se implementen. La herramienta se escribe en Python 3.11+
(ver [ADR-0001](docs/adr/0001-indexer-language.md)).

## Contribuir

Todavía no: el proyecto está en planificación y las primeras fases son personales. La Fase 7
abrirá la interfaz de parsers y la documentación para que la comunidad aporte adaptadores de
plugins. Si llegas desde el club, opiniones sobre el plan son bienvenidas desde ya.

## Nombre y comando

El repositorio y la herramienta se llaman **headless-vault-kit** (descriptivo, se explica
solo); el binario del CLI es **`hvk`** (`hvk search`, `hvk backlinks`, `hvk dv "..."`) —
repo largo y claro, comando corto y cómodo.

## Licencia

Pendiente de decidir antes de hacer el repositorio público (ver `.plans/`, Anexo).
