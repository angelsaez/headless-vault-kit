"""Shared fixtures: index a synthetic vault into a throwaway directory."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hvk import db, paths
from hvk import scan as scanner

VAULTS = Path(__file__).resolve().parent.parent / "test-vaults"


@pytest.fixture(scope="session")
def vaults() -> Path:
    return VAULTS


@pytest.fixture
def index(tmp_path):
    """Index a vault and hand back its locations and an open connection.

    Accepts a name under ``test-vaults/`` or an absolute path, so tests can point it at a
    vault they built themselves.
    """
    connections: list[sqlite3.Connection] = []

    def _index(vault, *, rebuild: bool = False):
        path = Path(vault)
        if not path.is_absolute():
            path = VAULTS / path
        location = paths.Locations(vault=path.resolve(), index_dir=tmp_path / f"{path.name}-index")
        stats = scanner.scan(location, rebuild=rebuild)
        conn = db.connect(location.db_path)
        connections.append(conn)
        return location, conn, stats

    yield _index
    for conn in connections:
        conn.close()


def links_of(conn: sqlite3.Connection, source: str) -> dict[int, sqlite3.Row]:
    """Every link written in *source*, keyed by line number."""
    rows = conn.execute(
        "SELECT l.line, l.target_raw, l.subpath, l.kind, l.embed, l.candidates, "
        "       t.path AS resolved "
        "FROM links l JOIN files f ON f.id = l.file_id "
        "LEFT JOIN files t ON t.id = l.target_file_id "
        "WHERE f.path = ?",
        (source,),
    ).fetchall()
    return {row["line"]: row for row in rows}


def props_of(conn: sqlite3.Connection, path_like: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT p.* FROM props p JOIN files f ON f.id = p.file_id "
        "WHERE f.path LIKE ? ORDER BY p.rowid",
        (path_like,),
    ).fetchall()


def prop(conn: sqlite3.Connection, path_like: str, key: str):
    row = conn.execute(
        "SELECT p.value, p.value_type FROM props p JOIN files f ON f.id = p.file_id "
        "WHERE f.path LIKE ? AND p.key = ?",
        (path_like, key),
    ).fetchone()
    return None if row is None else (row["value"], row["value_type"])
