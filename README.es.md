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

## Qué hace

No emular Obsidian: **replicar sus datos**. Todo lo que la app deriva al arrancar es estado
reconstruible desde los propios archivos. Este proyecto lo reconstruye en el servidor:

- **Indexador**: parsea el vault a SQLite igual que hace el metadata cache de la app
  (frontmatter, tags, enlaces, backlinks, tareas, encabezados, texto completo), con
  actualización incremental al ritmo del sync.
- **CLI `hvk`**: búsquedas, backlinks, tareas y propiedades en milisegundos, para
  que el agente consulte sin gastar tokens leyendo archivos.
- **Consultas sin app**: Bases (`.base`) ejecutado contra el índice, más vistas
  materializadas escritas como Markdown dentro de tus propias notas — visibles desde
  cualquier dispositivo.
- **Vault como cola**: notas-orden con estado en frontmatter; un runner las ejecuta con
  Claude Code y el resultado se sincroniza de vuelta a todos tus dispositivos.
- **Harness**: permisos, hooks y auditoría con los medios nativos de Claude Code + git.
- **Servidor MCP**: `hvk mcp` sirve el vault a cualquier cliente MCP por stdio — de solo lectura
  por defecto, y capaz de escribir solo si la instancia se arrancó con `--write`.

El criterio de alcance es un modelo de tres niveles: el comportamiento natural de la app se
replica exacto; los formatos oficiales de Obsidian (Bases, Canvas, plantillas) se soportan
completos; y los plugins de comunidad más usados entran solo si su estado vive en archivos
parseables — el resto, vía una [interfaz de parsers
extensible](CONTRIBUTING.md#writing-a-parser-adapter) para que cualquiera aporte el suyo. Los
tableros de Obsidian Kanban se leen por esa interfaz, como ejemplo trabajado. Nunca se ejecuta
código de plugins ni se reproduce la interfaz.

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
a Obsidian Sync. Eso tiene [su propio runbook](deploy/README.md) y su propia comprobación
previa — no empieces por ahí.

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
| `hvk canvas Tablero.canvas [--edges]` | Qué hay en un lienzo: sus cajas, o las flechas entre ellas |
| `hvk dql "LIST FROM #x"` \| `--note N.md` | Ejecuta una consulta Dataview, o cada bloque `dataview` de una nota, contra el índice |
| `hvk jobs --dir D --profiles P [--run]` | Ejecuta las notas-orden que esperan en un directorio; sin `--run` solo informa |
| `hvk doctor [--jobs-dir D]` | ¿Está sana esta instalación? Para llamarlo desde la monitorización que ya tengas |
| `hvk guard [--protect F]` | Hook `PreToolUse`: rechaza `rm` en favor de `.trash/`, las escrituras que caen fuera del vault, y las carpetas que designes. Los rechazos quedan registrados |
| `hvk mcp [--write] [--protect F]` | Sirve el vault a cualquier cliente MCP por stdio. Solo lectura salvo con `--write`, que añade las herramientas de escritura; se aplican las mismas reglas del guard y cada escritura queda registrada |
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
no ha cambiado nada. Las dos líneas, el runner de notas-orden y una copia de seguridad
nocturna los instala `deploy/install.sh` por ti.

La unit de systemd del watcher, y todo lo demás para levantar esto en un servidor, está en
[`deploy/`](deploy/).

Cuando esto llegue a PyPI, instalarlo será `uv tool install hvk` y nada más.

## La guía completa

Cada comando, para qué sirve cada pieza, los casos de uso y el vocabulario en dos idiomas:
**[docs/GUIDE.es.md](docs/GUIDE.es.md)** — in English, [docs/GUIDE.md](docs/GUIDE.md).

## Estructura del repositorio

```text
src/hvk/      El paquete: indexador, parsers, capa de escritura, servidor MCP y el CLI hvk
tests/        pytest, contra los vaults sintéticos de abajo
test-vaults/  Vaults sintéticos, con los casos incómodos: Unicode, YAML raro,
              encabezados duplicados, enlaces ambiguos y rotos
deploy/       Units de systemd de usuario, cron y el runbook para el servidor
tools/        Utilidades de desarrollo, no del producto (espejo del vault, testbed)
skills/       Skills de Claude Code, para que el agente sepa qué comando usar
docs/adr/     Decisiones de arquitectura: el «por qué» de cada elección de diseño
docs/         CHANGELOG.md, la bitácora del repositorio
```

Escrito en Python 3.11+ ([ADR-0001](docs/adr/0001-indexer-language.md)), con `ruamel.yaml` y
`watchdog` como únicas dependencias de ejecución.

## Contribuir

Los pull requests son bienvenidos, y también los informes de fallos y las preguntas.
**[CONTRIBUTING.md](CONTRIBUTING.md)** lo cuenta entero: cómo se corre la suite, las reglas que
no se negocian, la norma de una ADR por decisión, y cómo escribir un adaptador de parser para un
formato que esto todavía no lee.

Lo que se aporta queda bajo la MIT del propio proyecto, y no hay CLA.

Si vienes a leer el código, los tests son el mapa:

```bash
.venv/bin/pytest              # la suite, unos segundos
.venv/bin/pytest -m slow      # rendimiento, sobre un vault generado de 10 000 notas
```

Cada push y cada pull request pasan la suite en Python 3.11 y 3.13, instalan el paquete
construido con pip y con `uv tool install` y comprueban que cada uno responde contra un vault que
no ha visto nunca, y parsean todos los scripts de shell ([el workflow](.github/workflows/ci.yml)).
Solo en Linux: Linux es donde esto está pensado para correr.

El despliegue no se ejercita en CI: necesita una instancia de systemd de usuario y una máquina
desechable. Vive en [`tools/testbed/`](tools/testbed/), un contenedor Debian de usar y tirar, y
ahí es donde hay que pasar `deploy/selftest.sh` antes de fiarse de un cambio en `deploy/`.

## Nombre y comando

El repositorio y la herramienta se llaman **headless-vault-kit** (descriptivo, se explica
solo); el binario del CLI es **`hvk`** (`hvk search`, `hvk backlinks`, `hvk base "..."`) —
repo largo y claro, comando corto y cómodo.

## Hasta dónde llega

Qué está construido, qué queda pospuesto y cuán maduro es: [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Licencia

**MIT.** Haz con esto lo que quieras, incluido uso comercial; conserva el aviso de copyright, y
no hay garantía de ningún tipo. El texto completo está en [LICENSE](LICENSE).

Las dos dependencias de ejecución también son permisivas —`ruamel.yaml` es MIT y `watchdog` es
Apache-2.0—, así que nada de aquí condiciona lo que construyas encima.
