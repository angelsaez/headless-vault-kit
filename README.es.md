[English](README.md) | **Español**

# headless-vault-kit

> Devuelve la funcionalidad propia de Obsidian a un vault que vive en un servidor headless,
> donde la app nunca se abre: índice SQLite, backlinks, consultas Dataview y Bases, y
> automatización agéntica 24/7. El CLI se instala como **`hvk`**.

## El problema

Lleva un vault de Obsidian a un servidor headless —una máquina sin pantalla, para que un
agente y sus automatizaciones trabajen sobre las notas a todas horas— y los archivos llegan
sin problema: Obsidian Headless los mantiene sincronizados. Lo que no ocurre nunca es que
Obsidian se abra, y con ello se pierde todo lo que la app calcula al arrancar: backlinks,
consultas Dataview, Bases, el CLI, los plugins. Resultado: notas sincronizadas y nada que
sepa responder sobre ellas.

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

✅ **Fase 2 terminada.** El indexador de Nivel 0 parsea un vault a SQLite y responde búsquedas,
backlinks, enlaces, etiquetas, tareas, propiedades y huérfanos, con reconstrucción determinista.
Un watcher lo mantiene al día según Sync trae cambios, una pasada nocturna recalcula los hashes
como red de seguridad, y una [skill de Claude Code](skills/vault-queries/SKILL.md) le enseña al
agente qué comando responde cada pregunta.

Medido sobre un vault generado de 10 000 notas, contra los objetivos del propio plan, en
Ubuntu 26.04 y en Windows 11:

| Criterio | Objetivo | Medido en Linux | En Windows |
|---|---|---|---|
| Reconstrucción completa | < 60 s | **4,9 s** | 8,2 s |
| Actualización incremental | < 5 s | **0,34 s**, o 0,19 s dirigida | 0,76 s / 0,31 s |
| Consultas al índice | < 100 ms | **0,5 – 35 ms** | 0,8 – 80 ms |

Un criterio de salida de la fase no se puede cerrar desde un portátil: responder «¿qué notas
enlazan a X?» por Telegram de extremo a extremo depende de la Fase 0 en el servidor.

**La Fase 3 está en marcha.** Los `.base` se parsean y se ejecutan: `hvk base Library.base`
aplica filtros, fórmulas, orden y agrupación de una vista contra el índice y devuelve una tabla
Markdown. La [ADR-0005](docs/adr/0005-bases-subset.md) registra qué parte del lenguaje de
expresiones de Bases se soporta y qué se rechaza. Canvas queda pospuesto hasta que un vault
contenga de verdad un `.canvas`, y las notas periódicas esperan a una decisión, no a trabajo.

**La Fase 4 ya tiene su mitad valiosa.** Una nota puede llevar dentro la respuesta de un
`.base`, entre `<!-- vista:inicio -->` y `<!-- vista:fin -->`, de modo que la tabla se lee en el
móvil, donde nada renderiza un Base. `hvk views` dice qué está desactualizado y
`hvk views --apply` lo reescribe, tocando solo el texto entre los marcadores y sin escribir
nada cuando nada ha cambiado — que es lo que impide que un refresco cada media hora despierte a
Sync cada media hora en todos los dispositivos. Es lo primero aquí que escribe en un vault, así
que pasa por una única capa auditada
([ADR-0007](docs/adr/0007-writing-to-the-vault.md)); la sintaxis de la declaración está en la
[ADR-0008](docs/adr/0008-materialised-views.md). El subconjunto DQL de Dataview que la fase
prometía queda pospuesto indefinidamente: el vault para el que se escribió no tiene Dataview
instalado.

**La Fase 5 convierte el vault en la cola de trabajos.** Una nota en un directorio que tú
designas *es* un trabajo: su frontmatter es el estado, así que su progreso se lee en el móvil
como cualquier otra nota. `hvk jobs --run` reclama cada trabajo pendiente con una escritura que
declara el hash que la nota tenía al leerla —que es lo que hace que se ejecute exactamente una
vez aunque dos runners compitan o uno se reinicie a mitad—, lanza al agente y deja en la nota
el resultado y su causa.

Es además lo primero aquí que **ejecuta** algo porque lo diga una nota, y una nota puede llegar
de cualquier sitio. Por eso: todo trabajo nombra un perfil de permisos, elegido por nombre en
un directorio al que la nota no llega; los directorios de trabajos y de perfiles **no tienen
valor por defecto**, y nada se ejecuta hasta que alguien dice dónde están; y una salida dentro
del directorio de trabajos se rechaza, porque así es como un runner se da trabajo a sí mismo
para siempre. El razonamiento está en la [ADR-0009](docs/adr/0009-order-notes.md).

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
| `hvk watch` | Indexa los cambios según llegan, hasta que lo interrumpas; pensado para correr como servicio |
| `hvk verify` | Re-calcula el hash de todo como red de seguridad; se lanza de noche desde cron |
| `hvk base Archivo.base [--view Nombre]` | Ejecuta una vista de un `.base` contra el índice, como tabla Markdown |
| `hvk views [Ruta] [--apply]` | Regenera las tablas de Bases materializadas dentro de notas; sin `--apply` solo lista lo que está desactualizado |
| `hvk jobs --dir D --profiles P [--run]` | Ejecuta las notas-orden que esperan en un directorio; sin `--run` solo informa |
| `hvk info` | Qué contiene el índice ahora mismo |

Todos los comandos aceptan `--json` para salida legible por máquina; `hvk watch` emite JSON
Lines, un objeto por lote, para poder redirigirlo a un log.

Para mantener el índice al día: `hvk watch` como servicio y verificación nocturna por cron:

```cron
17 4 * * *   hvk --vault /ruta/al/vault verify
*/30 * * * *  hvk --vault /ruta/al/vault views --apply
```

La segunda línea es la que mantiene al día las vistas materializadas. Se puede lanzar tan a
menudo como se quiera: escribe solo lo que ha cambiado de verdad, y nada en absoluto cuando
no ha cambiado nada. Falta enchufarla en `deploy/`.

La unidad de systemd del watcher es trabajo de la Fase 0 y vivirá en `deploy/`.

Cuando la herramienta se publique, instalarla serán dos comandos y ningún `sudo`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install hvk
```

## Hoja de ruta

| Fase | Qué entrega | Estado |
|---|---|---|
| 0 | Base operativa en el VPS: Headless + Claude Code/Telegram + git, sobrevive a reinicios | Construida, sin ejecutar aún en un servidor |
| 1 | Inventario del vault: qué plugins y usos reales hay que cubrir | **Hecha** |
| 2 | Indexador Nivel 0 + CLI `hvk` | **Hecha** |
| 3 | Bases, Canvas, plantillas y notas periódicas | Bases **hecho**; el resto pospuesto |
| 4 | Vistas materializadas (DQL de Dataview pospuesto) | **Hecha** |
| 5 | Notas-orden: el vault como cola de trabajos | **Hecha** (Sync y Telegram esperan a la Fase 0) |
| 6 | Seguridad, healthchecks, backups ensayados | Pendiente |
| 7 | MCP + parsers de comunidad + empaquetado | Futuro |

## ¿Qué necesito para usarlo?

Depende de la capa — el proyecto se usa por trozos, con dependencias distintas:

| Capa | Qué hace | Qué requiere |
|---|---|---|
| Índice + CLI (Fases 2–4) | Búsqueda, backlinks, tareas, propiedades, consultas Bases/DQL, vistas materializadas | **Solo tus archivos** (cualquier vault de Obsidian o carpeta de Markdown) + el runtime. Sin IA, sin app, sin suscripciones. No consume ni un token |
| Sincronización | Vault actualizado en el servidor | Obsidian Sync + Obsidian Headless, **o** git como transporte. El índice no distingue cómo llegan los archivos |
| Automatización inteligente (Fase 5) | Notas-orden que requieren criterio ("revisa", "resume", "detecta") | Un agente CLI. **Claude Code es la opción soportada de serie**; los formatos (YAML, Markdown, SQLite) son neutrales y cambiar de agente es tocar una línea del runner. Las órdenes deterministas (regenerar vistas, crear la diaria) no necesitan agente |
| Acceso 24/7 por chat | Hablar con el vault desde el móvil | Claude Code + plugin de Telegram (o equivalente) |

Obsidian como aplicación solo hace falta donde siempre: en tus dispositivos, para leer
y escribir como humano.

## Requisitos del servidor de referencia

- VPS Linux (probado sobre 2 núcleos / 12 GB — sobra).
- Git.

## Estructura del repositorio

```text
.plans/     Planes de implementación (fuente de verdad del alcance)
docs/adr/   Decisiones de arquitectura (el «por qué» del diseño)
skills/     Skills de Claude Code, para que el agente sepa qué comando usar
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
plugins. Las opiniones sobre el plan son bienvenidas desde ya.

## Nombre y comando

El repositorio y la herramienta se llaman **headless-vault-kit** (descriptivo, se explica
solo); el binario del CLI es **`hvk`** (`hvk search`, `hvk backlinks`, `hvk dv "..."`) —
repo largo y claro, comando corto y cómodo.

## Licencia

Pendiente de decidir antes de hacer el repositorio público (ver `.plans/`, Anexo).
