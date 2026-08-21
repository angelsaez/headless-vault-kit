"""Locating the vault and its index directory.

Implements ADR-0002: the index lives outside the vault, one directory per vault, under
``$XDG_DATA_HOME/hvk`` by default, and hvk refuses to run if that directory would end up
inside the vault.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

DB_NAME = "index.sqlite"
LOG_NAME = "hvk.log"

# Files hvk reads by explicit path even though .obsidian/ is never indexed (ADR-0002, list A).
APP_JSON = ".obsidian/app.json"


class VaultError(Exception):
    """Raised when the vault or the index directory cannot be used as requested."""


@dataclass(frozen=True)
class Locations:
    """Where the vault is and where its index lives.

    The check that the index sits outside the vault lives here rather than only in
    :func:`resolve`, because it is the condition that prevents sync/watcher feedback loops
    (ADR-0002) and must not be bypassable by building this object directly.
    """

    vault: Path
    index_dir: Path

    def __post_init__(self) -> None:
        if self.index_dir == self.vault or self.index_dir.is_relative_to(self.vault):
            raise VaultError(
                f"the index directory would sit inside the vault ({self.index_dir}). That is "
                f"what causes sync/watcher feedback loops, so hvk refuses to run. Choose a "
                f"path outside {self.vault}."
            )

    @property
    def db_path(self) -> Path:
        return self.index_dir / DB_NAME

    @property
    def log_path(self) -> Path:
        return self.index_dir / LOG_NAME


def find_vault(start: Path | None = None) -> Path:
    """Walk up from *start* until a directory containing ``.obsidian/`` is found.

    Discovery needs a marker; an explicit ``--vault`` does not, so that plain Markdown
    folders can be indexed too.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".obsidian").is_dir():
            return candidate
    raise VaultError(
        f"no vault found at or above {current}: none of those directories contains "
        f".obsidian/. Pass --vault explicitly, or set HVK_VAULT."
    )


def index_root() -> Path:
    """Root under which per-vault index directories are created."""
    override = os.environ.get("HVK_INDEX_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "hvk"


def vault_slug(vault: Path) -> str:
    """Readable, filesystem-safe identifier for a vault directory name."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", vault.name).strip("-.")
    slug = slug[:40].lower()
    return slug or "vault"


def index_dir_for(vault: Path) -> Path:
    """Default index directory for *vault*: ``<root>/<slug>-<hash8 of the real path>``.

    The hash keeps two vaults with the same name in different places apart. Moving a vault
    changes its resolved path and therefore its index directory, which means a rebuild --
    correct, because the index is derived, but it has to be documented.
    """
    digest = hashlib.sha256(str(vault.resolve()).encode("utf-8")).hexdigest()[:8]
    return index_root() / f"{vault_slug(vault)}-{digest}"


def resolve(vault: Path | None = None, index: Path | None = None) -> Locations:
    """Resolve vault and index directory from arguments, environment and discovery.

    Precedence is the one fixed by ADR-0002: explicit argument, then environment, then the
    default. The index directory is never allowed to sit inside the vault.
    """
    if vault is not None:
        vault_path = Path(vault).expanduser().resolve()
        if not vault_path.is_dir():
            raise VaultError(f"vault path is not a directory: {vault_path}")
    elif os.environ.get("HVK_VAULT"):
        vault_path = Path(os.environ["HVK_VAULT"]).expanduser().resolve()
        if not vault_path.is_dir():
            raise VaultError(f"HVK_VAULT is not a directory: {vault_path}")
    else:
        vault_path = find_vault()

    index_dir = Path(index).expanduser().resolve() if index is not None else index_dir_for(vault_path)

    # Both paths are resolved before Locations checks them, because a symlinked index
    # directory inside the vault would loop just as happily as a real one.
    return Locations(vault=vault_path, index_dir=index_dir)


def read_app_json(vault: Path) -> dict:
    """Read ``.obsidian/app.json``, or return an empty dict when it is absent or invalid.

    Per ADR-0003 these settings govern how links are *written*, not how they are read, so a
    missing file never blocks indexing.
    """
    path = vault / APP_JSON
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
