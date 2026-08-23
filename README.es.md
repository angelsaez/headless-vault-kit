[English](README.md) | **Español**

# headless-vault-kit

> Devuelve la funcionalidad propia de Obsidian a un vault que vive en un servidor headless,
> donde la app nunca se abre: índice SQLite, backlinks, consultas de Bases, y
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
- **Consultas sin app**: Bases (`.base`) ejecutado contra el índice, más vistas
  materializadas escritas como Markdown dentro de tus propias notas — visibles desde
  cualquier dispositivo. El subconjunto de Dataview (DQL) estaba planificado y queda
  pospuesto; mira la hoja de ruta.
- **Vault como cola**: notas-orden con estado en frontmatter; un runner las ejecuta con
  Claude Code y el resultado se sincroniza de vuelta a todos tus dispositivos.
- **Harness**: permisos, hooks y auditoría con los medios nativos de Claude Code + git.

El criterio de alcance es un modelo de tres niveles: el comportamiento natural de la app se
replica exacto; los formatos oficiales de Obsidian (Bases, Canvas, plantillas) se soportan
completos; y los plugins de comunidad más usados entran solo si su estado vive en archivos
parseables — el resto, vía una interfaz de parsers extensible para que cualquiera aporte
el suyo. Nunca se ejecuta código de plugins ni se reproduce la interfaz.

## Estado

**Fases 1, 2, 4 y 5 hechas, más la mitad de Bases de la fase 3.** Lo que no está hecho es la
fase 0 —ejecutarlo en un servidor de verdad— y hasta que eso ocurra nadie, ni su propio autor,
lo ha usado en producción un solo día. Lee la hoja de ruta antes de confiarle nada.

✅ **Fase 2.** El indexador de Nivel 0 parsea un vault a SQLite y responde búsquedas,
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

## Requisitos

Hay dos cosas distintas que puedes querer, y piden cantidades muy distintas.

**Para usar el comando `hvk`** — indexar un vault, hacerle preguntas, materializar vistas,
ejecutar trabajos:

| | |
|---|---|
| Python | **3.11 o superior**, y nada más |
| Sistema operativo | Linux, macOS o Windows. Probado en Linux y en Windows |
| Obsidian | **No hace falta.** hvk lee los archivos; la app no tiene que estar instalada ni abierta |
| Un vault | Cualquier carpeta con Markdown. El directorio `.obsidian/` solo se necesita si quieres que hvk encuentre el vault por sí solo |

**Para levantar el sistema 24/7 en un servidor** — sync, un agente en Telegram, trabajos
programados— además necesitas Linux con systemd, Node.js 22+, Bun, tmux, git y una suscripción
a Obsidian Sync. Eso es la fase 0, con [su propio runbook](deploy/README.md) y su propia
comprobación previa. No empieces por ahí.

## Instalación

Todavía no está en PyPI, así que las dos vías instalan desde este repositorio. Elige una.

**A. Como comando, con [uv](https://docs.astral.sh/uv/)** — recomendada si solo quieres
usarlo. `hvk` queda en tu `PATH`, en su propio entorno aislado:

```bash
uv tool install --from git+https://github.com/angelsaez/headless-vault-kit headless-vault-kit
```

`uv tool upgrade headless-vault-kit` lo actualiza después; `uv tool uninstall headless-vault-kit`
lo quita del todo.

**B. Desde un clon** — si quieres leer el código, cambiarlo o pasar los tests:

```bash
git clone https://github.com/angelsaez/headless-vault-kit
cd headless-vault-kit
python -m venv .venv
```

Y después, en Linux o macOS:

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/hvk --version
```

En Windows (PowerShell):

```powershell
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\hvk --version
```

En Git Bash usa barras normales: `.venv/Scripts/pip`, `.venv/Scripts/hvk`.

El `[dev]` añade pytest y nada más. Puedes omitirlo si no vas a pasar los tests.

## Comprobar que funciona

Apúntalo a un vault —uno real vale, hvk solo lee, y su índice se escribe fuera del vault
([ADR-0002](docs/adr/0002-index-location.md))—:

```bash
hvk --vault /ruta/al/vault scan
hvk --vault /ruta/al/vault info
hvk --vault /ruta/al/vault backlinks "Una nota"
```

`scan` dice cuántos archivos indexó y cuánto tardó; con unos cientos de notas eso es bastante
menos de un segundo. Si `backlinks` nombra las notas que esperabas, todo lo de más abajo
funciona también.

Dos cosas que conviene saber desde el principio:

- **Ejecutándolo dentro de un vault puedes omitir `--vault`.** hvk sube por el árbol desde el
  directorio actual hasta encontrar una carpeta `.obsidian/`.
- **`hvk rebuild` siempre es seguro.** El índice se deriva de tus archivos y de nada más, así
  que borrarlo cuesta tiempo y nada más. Nada de `scan`, `search`, `backlinks`, `links`,
  `tags`, `tasks`, `props`, `orphans`, `base` o `info` escribe jamás en tu vault; solo lo hacen
  `views --apply` y `jobs --run`, y ambos lo dicen en su nombre.

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

Cuando esto llegue a PyPI, instalarlo será `uv tool install hvk` y nada más. Eso pertenece a la
Fase 7, que el plan mantiene detrás de semanas de estabilidad real y no de una sensación de
estar listo.

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

Todavía no: las primeras fases son personales y el sistema no ha corrido en un servidor ni un
día. La Fase 7 abrirá la interfaz de parsers y la documentación para que la comunidad aporte
adaptadores de plugins. Las opiniones sobre el plan son bienvenidas desde ya.

Si vienes a leer el código, los tests son el mapa:

```bash
.venv/bin/pytest              # la suite, unos segundos
.venv/bin/pytest -m slow      # los criterios numéricos del plan, sobre un vault generado de 10 000 notas
```

Cada push y cada pull request pasan la suite en Python 3.11 y 3.13, instalan el paquete
construido y comprueban que responde contra un vault que no ha visto nunca, y parsean todos los
scripts de shell ([el workflow](.github/workflows/ci.yml)). Solo en Linux, por decisión del
propio plan: el servidor es Linux, y una matriz de tres sistemas operativos fue uno de los
costes que la v2 eliminó.

El despliegue no se ejercita ahí: necesita una instancia de systemd de usuario y una máquina
desechable. Vive en [`tools/testbed/`](tools/testbed/), un contenedor Debian de usar y tirar, y
ahí es donde hay que pasar `deploy/selftest.sh` antes de fiarse de un cambio en `deploy/`.

## Nombre y comando

El repositorio y la herramienta se llaman **headless-vault-kit** (descriptivo, se explica
solo); el binario del CLI es **`hvk`** (`hvk search`, `hvk backlinks`, `hvk base "..."`) —
repo largo y claro, comando corto y cómodo.

## Licencia

Pendiente de decidir antes de hacer el repositorio público (ver `.plans/`, Anexo).
