"""Vault discovery, index location and the safety rule of ADR-0002."""

from __future__ import annotations

import pytest

from hvk import paths


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "MyVault"
    (root / ".obsidian").mkdir(parents=True)
    (root / "Sub" / "Deeper").mkdir(parents=True)
    return root


def test_discovery_walks_up_to_the_obsidian_marker(vault, monkeypatch):
    monkeypatch.chdir(vault / "Sub" / "Deeper")
    assert paths.find_vault() == vault.resolve()


def test_discovery_fails_with_an_actionable_message(tmp_path, monkeypatch):
    plain = tmp_path / "not-a-vault"
    plain.mkdir()
    monkeypatch.chdir(plain)
    with pytest.raises(paths.VaultError, match="--vault"):
        paths.find_vault()


def test_index_directory_is_readable_and_unique(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("HVK_INDEX_DIR", str(tmp_path / "root"))
    first = paths.index_dir_for(vault)
    assert first.name.startswith("myvault-")
    assert first.parent == (tmp_path / "root")

    twin = tmp_path / "elsewhere" / "MyVault"
    (twin / ".obsidian").mkdir(parents=True)
    assert paths.index_dir_for(twin) != first, "same name, different path, different index"


def test_index_inside_the_vault_is_refused(vault):
    with pytest.raises(paths.VaultError, match="inside the vault"):
        paths.resolve(vault, vault / ".hvk")


def test_index_equal_to_the_vault_is_refused(vault):
    with pytest.raises(paths.VaultError, match="inside the vault"):
        paths.resolve(vault, vault)


def test_a_symlinked_index_inside_the_vault_is_refused(vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = vault / "sneaky"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not allow creating symlinks here")
    # Resolving the symlink lands outside the vault, so this one is legitimately allowed;
    # what must not happen is the reverse, checked below.
    assert paths.resolve(vault, link).index_dir == outside.resolve()

    inside = tmp_path / "points-in"
    try:
        inside.symlink_to(vault / "Sub", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not allow creating symlinks here")
    with pytest.raises(paths.VaultError, match="inside the vault"):
        paths.resolve(vault, inside)


def test_explicit_vault_does_not_need_the_marker(tmp_path):
    plain = tmp_path / "just-markdown"
    plain.mkdir()
    assert paths.resolve(plain, tmp_path / "idx").vault == plain.resolve()


def test_environment_is_used_when_no_argument_is_given(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("HVK_VAULT", str(vault))
    monkeypatch.setenv("HVK_INDEX_DIR", str(tmp_path / "root"))
    location = paths.resolve()
    assert location.vault == vault.resolve()
    assert location.index_dir.parent == tmp_path / "root"


def test_app_json_is_read_by_path_not_indexed(vault):
    (vault / ".obsidian" / "app.json").write_text(
        '{"newLinkFormat": "shortest"}', encoding="utf-8"
    )
    assert paths.read_app_json(vault)["newLinkFormat"] == "shortest"


def test_missing_app_json_is_not_an_error(vault):
    assert paths.read_app_json(vault) == {}


def test_db_and_log_live_in_the_index_directory(vault, tmp_path):
    location = paths.resolve(vault, tmp_path / "idx")
    assert location.db_path == tmp_path / "idx" / "index.sqlite"
    assert location.log_path == tmp_path / "idx" / "hvk.log"
