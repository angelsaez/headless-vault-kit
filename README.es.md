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

🚧 **Fase de planificación.** Aún no hay código. El plan completo, con fases y criterios de
salida, está en [`.plans/Plan-v2-headless-vault-kit.md`](.plans/Plan-v2-headless-vault-kit.md).

## Hoja de ruta

| Fase | Qué entrega | Estado |
|---|---|---|
| 0 | Base operativa en el VPS: Headless + Claude Code/Telegram + git, sobrevive a reinicios | Pendiente |
| 1 | Inventario del vault: qué plugins y usos reales hay que cubrir | Pendiente |
| 2 | Indexador Nivel 0 + CLI `hvk` | Pendiente |
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
CLAUDE.md   Guía para el agente que desarrolla y opera este repo
README.md   Versión en inglés (por defecto) · README.es.md este archivo
```

El resto de carpetas (`indexer/`, `cli/`, `runner/`, `deploy/`, `docs/adr/`, `test-vaults/`)
irán apareciendo a medida que sus fases se implementen.

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
