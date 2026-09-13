"""Tests for release packaging, focused on wiping personal data fresh."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from config.constants import LOG_DIR_NAME, PLUGINS_DIR_NAME, USERDATA_DIR_NAME

import aphelion_build
from aphelion_build import (CUSTOM_NODES_FILENAME, PREFERENCES_FILENAME,
                            RECENT_PROJECTS_FILENAME, BuildError,
                            StagedAppData, freeze_include_files,
                            fresh_userdata_documents, reset_tree_app_data,
                            stage_fresh_userdata, unexpected_app_data_paths,
                            verify_tree_app_data)


class _FakeRecord:
    """Minimal ``msilib`` record exposing ``GetString``."""

    def __init__(self, values: tuple[str, ...]) -> None:
        self._values = values

    def GetString(self, index: int) -> str:
        return self._values[index - 1]


class _FakeView:
    """Minimal ``msilib`` view over a fixed row list."""

    def __init__(self, rows: list[tuple[str, ...]]) -> None:
        self._rows = list(rows)

    def Execute(self, _params: object) -> None:
        return

    def Fetch(self) -> _FakeRecord | None:
        if not self._rows:
            return None
        return _FakeRecord(self._rows.pop(0))

    def Close(self) -> None:
        return


class _FakeDatabase:
    """Minimal ``msilib`` database that answers by table name."""

    def __init__(self, tables: dict[str, list[tuple[str, ...]]]) -> None:
        self._tables = tables

    def OpenView(self, sql: str) -> _FakeView:
        for table, rows in self._tables.items():
            if f"`{table}`" in sql:
                return _FakeView(rows)
        raise AssertionError(f"unexpected query: {sql}")


class StagedUserdataTests(unittest.TestCase):
    """Verify the pristine payload a build bundles."""

    def setUp(self) -> None:
        """Create a scratch staging root."""
        self._tmp = TemporaryDirectory()
        self.stage_root = Path(self._tmp.name)

    def tearDown(self) -> None:
        """Release the scratch root."""
        self._tmp.cleanup()

    def test_stage_writes_pristine_documents(self) -> None:
        """Staging produces valid, empty documents and the plugin folder."""
        staged: StagedAppData = stage_fresh_userdata(self.stage_root)

        self.assertTrue(staged.userdata.is_dir())
        self.assertTrue(staged.logs.is_dir())
        self.assertTrue((staged.userdata / PLUGINS_DIR_NAME).is_dir())

        recent = json.loads(
            (staged.userdata / RECENT_PROJECTS_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(recent, {"projects": []})

        custom = json.loads(
            (staged.userdata / CUSTOM_NODES_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(custom["definitions"], [])
        self.assertEqual(custom["format"], aphelion_build.CUSTOM_NODES_FORMAT_ID)

        preferences = json.loads(
            (staged.userdata / PREFERENCES_FILENAME).read_text(encoding="utf-8")
        )
        self.assertIsInstance(preferences, dict)
        self.assertTrue(preferences)

    def test_stage_matches_the_editor_defaults(self) -> None:
        """Shipped documents must match what the editor writes on first run."""
        from core.boot.recent import RECENT_PROJECTS_FILENAME as RECENT_CONST
        from core.custom_node_store import (
            CUSTOM_NODES_FILENAME as CUSTOM_CONST,
            CUSTOM_NODES_FORMAT_ID as FORMAT_CONST,
            CUSTOM_NODES_FORMAT_VERSION as VERSION_CONST,
        )
        from core.preferences.models import AppPreferences
        from core.preferences.store import PREFERENCES_FILENAME as PREF_CONST

        self.assertEqual(RECENT_PROJECTS_FILENAME, RECENT_CONST)
        self.assertEqual(CUSTOM_NODES_FILENAME, CUSTOM_CONST)
        self.assertEqual(PREFERENCES_FILENAME, PREF_CONST)
        self.assertEqual(aphelion_build.CUSTOM_NODES_FORMAT_ID, FORMAT_CONST)
        self.assertEqual(
            aphelion_build.CUSTOM_NODES_FORMAT_VERSION, VERSION_CONST
        )
        self.assertEqual(
            fresh_userdata_documents()[PREFERENCES_FILENAME],
            dict(AppPreferences.defaults().to_dict()),
        )

    def test_restaging_removes_previous_content(self) -> None:
        """A second stage wipes files left behind by an earlier build."""
        staged: StagedAppData = stage_fresh_userdata(self.stage_root)
        stale = staged.userdata / "recent_projects.json"
        stale.write_text('{"projects": [{"path": "C:/leak.aph"}]}', encoding="utf-8")
        cache = staged.userdata / "__pycache__"
        cache.mkdir()
        (cache / "junk.pyc").write_text("x", encoding="utf-8")
        (staged.logs / "aphelion.log").write_text("session", encoding="utf-8")

        restaged: StagedAppData = stage_fresh_userdata(self.stage_root)

        self.assertEqual(
            json.loads(
                (restaged.userdata / RECENT_PROJECTS_FILENAME).read_text(
                    encoding="utf-8"
                )
            ),
            {"projects": []},
        )
        self.assertFalse((restaged.userdata / "__pycache__").exists())
        self.assertFalse((restaged.logs / "aphelion.log").exists())


class FreezeIncludeFilesTests(unittest.TestCase):
    """Verify the working tree's userdata can never be bundled."""

    def setUp(self) -> None:
        """Stage into a scratch root and point the module at it."""
        self._tmp = TemporaryDirectory()
        self.stage_root = Path(self._tmp.name)
        self._original_stage = aphelion_build.PACKAGING_STAGE_DIR
        aphelion_build.PACKAGING_STAGE_DIR = self.stage_root

    def tearDown(self) -> None:
        """Restore the staging root."""
        aphelion_build.PACKAGING_STAGE_DIR = self._original_stage
        self._tmp.cleanup()

    def test_userdata_and_logs_are_replaced_by_staged_copies(self) -> None:
        """``userdata/`` and ``logs/`` never resolve to the working tree."""
        pairs = dict(
            (destination, source) for source, destination in freeze_include_files()
        )

        repo_root = Path(aphelion_build.REPO_ROOT).resolve()
        userdata_source = Path(pairs[f"{USERDATA_DIR_NAME}/"]).resolve()
        logs_source = Path(pairs[f"{LOG_DIR_NAME}/"]).resolve()

        self.assertTrue(userdata_source.is_dir())
        self.assertTrue(logs_source.is_dir())
        self.assertEqual(userdata_source.parent, self.stage_root.resolve())
        self.assertNotEqual(userdata_source, (repo_root / USERDATA_DIR_NAME).resolve())
        self.assertNotEqual(logs_source, (repo_root / LOG_DIR_NAME).resolve())
        self.assertFalse(
            (userdata_source / RECENT_PROJECTS_FILENAME)
            .read_text(encoding="utf-8")
            .find("Untitled") >= 0
        )

    def test_other_assets_still_come_from_the_repository(self) -> None:
        """Resources and bundled plugins keep their declarative sources."""
        pairs = freeze_include_files()
        self.assertIn(("resources/", "resources/"), pairs)
        self.assertIn(("plugins/", "plugins/"), pairs)

    def test_extra_pairs_are_appended(self) -> None:
        """Installer extras (SDK wheel, helper script) survive the swap."""
        pairs = freeze_include_files(("wheel.whl", "sdk/wheel.whl"))
        self.assertEqual(pairs[-1], ("wheel.whl", "sdk/wheel.whl"))


class BuiltTreeAppDataTests(unittest.TestCase):
    """Verify the post-freeze reset and inspection of a built tree."""

    def setUp(self) -> None:
        """Create a fake frozen tree that carries personal data."""
        self._tmp = TemporaryDirectory()
        self.tree = Path(self._tmp.name) / "exe.fake"
        self.userdata = self.tree / USERDATA_DIR_NAME
        (self.userdata / PLUGINS_DIR_NAME).mkdir(parents=True)
        self.logs = self.tree / LOG_DIR_NAME
        self.logs.mkdir(parents=True)

        (self.userdata / RECENT_PROJECTS_FILENAME).write_text(
            json.dumps(
                {"projects": [{"path": "C:/Users/dev/Secret.aph", "name": "Secret"}]}
            ),
            encoding="utf-8",
        )
        (self.userdata / "notes.py").write_text("# plugin", encoding="utf-8")
        (self.logs / "aphelion.log").write_text("session", encoding="utf-8")
        self._original_stage = aphelion_build.PACKAGING_STAGE_DIR
        aphelion_build.PACKAGING_STAGE_DIR = Path(self._tmp.name) / "_stage"

    def tearDown(self) -> None:
        """Restore the staging root and release the tree."""
        aphelion_build.PACKAGING_STAGE_DIR = self._original_stage
        self._tmp.cleanup()

    def test_verify_rejects_personal_documents(self) -> None:
        """A tree copied from the working tree fails verification."""
        with self.assertRaises(BuildError) as caught:
            verify_tree_app_data(self.tree)
        message = str(caught.exception)
        self.assertIn("notes.py", message)

    def test_verify_rejects_personal_document_contents(self) -> None:
        """A same-named but personal document is caught by its contents."""
        (self.userdata / "notes.py").unlink()
        with self.assertRaises(BuildError) as caught:
            verify_tree_app_data(self.tree)
        message = str(caught.exception)
        self.assertIn(RECENT_PROJECTS_FILENAME, message)
        self.assertIn("recent project", message)

    def test_verify_accepts_the_pristine_payload(self) -> None:
        """The staged payload verifies once it is copied into the tree."""
        reset_tree_app_data(self.tree)
        verify_tree_app_data(self.tree)

    def test_verify_rejects_user_plugins_and_logs(self) -> None:
        """User plugins and session logs are rejected too."""
        reset_tree_app_data(self.tree)
        (self.userdata / PLUGINS_DIR_NAME / "notes.py").write_text(
            "# personal plugin", encoding="utf-8"
        )
        with self.assertRaises(BuildError):
            verify_tree_app_data(self.tree)
        (self.userdata / PLUGINS_DIR_NAME / "notes.py").unlink()

        (self.logs / "aphelion.log.1").write_text("old session", encoding="utf-8")
        with self.assertRaises(BuildError):
            verify_tree_app_data(self.tree)

    def test_reset_makes_the_tree_verifiable(self) -> None:
        """Resetting rewrites the folders so verification passes."""
        rewritten = reset_tree_app_data(self.tree)

        self.assertEqual(len(rewritten), 2)
        verify_tree_app_data(self.tree)
        self.assertFalse((self.userdata / "notes.py").exists())
        self.assertFalse((self.logs / "aphelion.log").exists())

    def test_reset_leaves_unrelated_trees_alone(self) -> None:
        """Trees without app-data folders are untouched."""
        other = Path(self._tmp.name) / "exe.bare"
        other.mkdir()
        self.assertEqual(reset_tree_app_data(other), [])
        verify_tree_app_data(other)


class InstallerPayloadTests(unittest.TestCase):
    """Verify the MSI inspection that guards the finished installer."""

    def test_unexpected_paths_flags_logs_and_user_plugins(self) -> None:
        """Name-level inspection catches logs, caches, and user plugins."""
        offenders = unexpected_app_data_paths(
            [
                "AphelionEditor.exe",
                "resources/icon.ico",
                "userdata/preferences.json",
                "userdata/recent_projects.json",
                "userdata/__pycache__/notes.cpython-314.pyc",
                "userdata/plugins/README.txt",
                "userdata/plugins/notes.py",
                "logs/aphelion.log",
                "logs/aphelion.log.1",
            ]
        )
        self.assertEqual(
            offenders,
            [
                "logs/aphelion.log",
                "logs/aphelion.log.1",
                "userdata/__pycache__/notes.cpython-314.pyc",
                "userdata/plugins/notes.py",
            ],
        )

    def test_unexpected_paths_accepts_a_pristine_payload(self) -> None:
        """The staged payload passes inspection."""
        self.assertEqual(
            unexpected_app_data_paths(
                [
                    "AphelionEditor.exe",
                    f"userdata/{RECENT_PROJECTS_FILENAME}",
                    f"userdata/{CUSTOM_NODES_FILENAME}",
                    f"userdata/{PREFERENCES_FILENAME}",
                    "userdata/README.txt",
                    f"userdata/{PLUGINS_DIR_NAME}/README.txt",
                    "logs/README.txt",
                ]
            ),
            [],
        )

    def test_msi_file_paths_rebuilds_install_locations(self) -> None:
        """Short|long names and the component chain resolve to real paths."""
        database = _FakeDatabase(
            {
                "Directory": [
                    ("TARGETDIR", "", "SourceDir"),
                    ("userdata", "TARGETDIR", "USERDATA|userdata"),
                    ("plugins1", "userdata", "PLUGINS|plugins"),
                    ("logs", "TARGETDIR", "LOGS|logs"),
                ],
                "Component": [
                    ("C_recent", "userdata"),
                    ("C_plugin", "plugins1"),
                    ("C_log", "logs"),
                ],
                "File": [
                    (
                        "recent_projects.json",
                        "C_recent",
                        "RECENT~1.JSO|recent_projects.json",
                    ),
                    ("notes.py", "C_plugin", "NOTES.PY|notes.py"),
                    ("aphelion.log", "C_log", "APHELION.LOG|aphelion.log"),
                ],
            }
        )
        paths = aphelion_build._msi_file_paths(database)
        self.assertEqual(
            paths,
            [
                "userdata/recent_projects.json",
                "userdata/plugins/notes.py",
                "logs/aphelion.log",
            ],
        )
        self.assertEqual(
            unexpected_app_data_paths(paths),
            ["logs/aphelion.log", "userdata/plugins/notes.py"],
        )


if __name__ == "__main__":
    unittest.main()
