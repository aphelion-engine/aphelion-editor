"""Tests for SDK editor discovery and drop-in plugin install."""

from __future__ import annotations

from pathlib import Path

import pytest

from aphelion_sdk.host.constants import ENV_EDITOR_HOME
from aphelion_sdk.host.errors import EditorHostError
from aphelion_sdk.host.install import install_plugins_into_editor
from aphelion_sdk.host.locate import locate_editor
from aphelion_sdk.host.models import EditorInstall
from aphelion_sdk.host.validate import install_from_root


def test_install_from_root_accepts_source_checkout(tmp_path: Path) -> None:
    """A directory with ``main.py`` must count as a source editor install."""
    (tmp_path / "main.py").write_text("# editor\n", encoding="utf-8")
    found = install_from_root(tmp_path, source="test")
    assert found is not None
    assert found.is_frozen is False
    assert found.root == tmp_path.resolve()


def test_install_from_root_accepts_frozen_tree(tmp_path: Path) -> None:
    """A directory with ``AphelionEditor.exe`` must count as a frozen install."""
    exe = tmp_path / "AphelionEditor.exe"
    exe.write_bytes(b"mz")
    found = install_from_root(tmp_path, source="test")
    assert found is not None
    assert found.is_frozen is True
    assert found.executable == exe.resolve()


def test_locate_editor_prefers_env_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``APHELION_EDITOR_HOME`` must win over sibling discovery."""
    (tmp_path / "main.py").write_text("# editor\n", encoding="utf-8")
    monkeypatch.setenv(ENV_EDITOR_HOME, str(tmp_path))
    found: EditorInstall = locate_editor()
    assert found.root == tmp_path.resolve()
    assert found.source == "environment"


def test_locate_editor_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery must fail clearly when no editor is present."""
    monkeypatch.delenv(ENV_EDITOR_HOME, raising=False)
    monkeypatch.setattr(
        "aphelion_sdk.host.locate._candidate_roots",
        lambda: (),
    )
    with pytest.raises(EditorHostError):
        locate_editor()


def test_install_plugins_into_editor_copies_file(tmp_path: Path) -> None:
    """Drop-in plugin files must land in the install's userdata/plugins."""
    editor_root = tmp_path / "editor"
    editor_root.mkdir()
    (editor_root / "main.py").write_text("# editor\n", encoding="utf-8")
    plugin = tmp_path / "demo.py"
    plugin.write_text("import aphelion_sdk\n", encoding="utf-8")
    install = install_from_root(editor_root, source="test")
    assert install is not None
    written = install_plugins_into_editor(plugin, editor=install)
    assert len(written) == 1
    assert written[0].name == "demo.py"
    assert written[0].is_file()
    assert written[0].parent == install.user_plugin_dir
