"""Verify a built Aphelion Editor MSI.

Two things are checked, both because they have silently broken before:

1. **Every dialog's ``Control_Next`` chain is a single cycle covering all of
   the dialog's controls.** Windows Installer fails the install with error 2810
   otherwise, and it fails *at install time on the user's machine*, so a build
   that produced a file is not evidence that the installer works. The real
   defect was ``OptionsDlg``, where two controls both pointed at ``InstallScope``
   and ``Next -> Cancel -> Back -> Next`` closed an inner loop.

2. **The bundled native module is present.** ``aphelion_native.pyd`` is built
   into ``src/`` and copied in by ``freeze_include_files()``. When the build
   could not find it, cx_Freeze froze a package without it and the result looked
   like a successful installer.

The product version is compared against ``APP_VERSION`` as well, because the two
drift apart quietly — the installer carried 0.1.0 while the application had
moved on to 0.1.2.

Usage::

    python scripts/verify_msi.py                     # newest MSI in releases/
    python scripts/verify_msi.py path/to/setup.msi
"""

from __future__ import annotations

import sys
from pathlib import Path

EDITOR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EDITOR_ROOT / "src"))

from msilib import MSIDBOPEN_READONLY, OpenDatabase  # noqa: E402

from config.constants import APP_VERSION  # noqa: E402


def newest_msi() -> Path | None:
    candidates = sorted(
        (EDITOR_ROOT / "releases").glob("*.msi"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def rows(database, sql: str, columns: int) -> list[tuple[str, ...]]:
    view = database.OpenView(sql)
    view.Execute(None)
    out: list[tuple[str, ...]] = []
    while True:
        record = view.Fetch()
        if record is None:
            break
        out.append(tuple(record.GetString(i + 1) or "" for i in range(columns)))
    view.Close()
    return out


def cycle_diagnosis(controls: list[tuple[str, str]]) -> tuple[bool, str]:
    """Is ``Control_Next`` one cycle covering every control on the dialog?"""
    successors = dict(controls)
    names = list(successors)

    incoming: dict[str, list[str]] = {}
    for name, nxt in successors.items():
        incoming.setdefault(nxt, []).append(name)

    duplicated = {target: src for target, src in incoming.items() if len(src) > 1}
    if duplicated:
        detail = "; ".join(
            f"{target} <- {', '.join(src)}" for target, src in duplicated.items()
        )
        return False, f"duplicate next pointers: {detail}"

    start = names[0]
    seen: list[str] = []
    current = start
    while current not in seen:
        seen.append(current)
        current = successors.get(current, "")
        if not current:
            return False, f"chain from {start} dead-ends at {seen[-1]}"
    if current != start:
        return False, f"chain from {start} closes at {current}, not {start}"
    if len(seen) != len(successors):
        missing = sorted(set(successors) - set(seen))
        return False, f"controls outside the cycle: {', '.join(missing)}"
    return True, f"{len(seen)} controls, single cycle"


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        msi = Path(argv[1])
    else:
        found = newest_msi()
        if found is None:
            print("no .msi in releases/ — build one first, or pass a path")
            return 1
        msi = found

    if not msi.is_file():
        print(f"missing: {msi}")
        return 1

    failures: list[str] = []
    database = OpenDatabase(str(msi), MSIDBOPEN_READONLY)
    try:
        print(f"=== {msi.name} ===")

        control_rows = rows(
            database, "SELECT `Dialog_`, `Control`, `Control_Next` FROM `Control`", 3
        )
        dialogs: dict[str, list[tuple[str, str]]] = {}
        for dialog, control, control_next in control_rows:
            dialogs.setdefault(dialog, []).append((control, control_next))

        print(f"dialogs with controls: {len(dialogs)}")
        for dialog in sorted(dialogs):
            ok, detail = cycle_diagnosis(dialogs[dialog])
            if not ok:
                failures.append(f"{dialog}: {detail}")
            print(f"  {'OK  ' if ok else 'FAIL'} {dialog:<24} {detail}")

        properties = dict(rows(database, "SELECT `Property`, `Value` FROM `Property`", 2))
        version = properties.get("ProductVersion", "")
        version_ok = version == APP_VERSION
        if not version_ok:
            failures.append(
                f"ProductVersion is {version!r}, APP_VERSION is {APP_VERSION!r}"
            )
        print(
            f"\nproduct version: {version!r} "
            f"({'matches' if version_ok else 'MISMATCH with'} APP_VERSION {APP_VERSION!r})"
        )

        files = rows(database, "SELECT `File`, `FileName` FROM `File`", 2)
        native = [name for _, name in files if "aphelion_native" in name.lower()]
        if not native:
            failures.append("no aphelion_native entry in the File table")
        print(f"files in the package: {len(files)}")
        print(f"native module entries: {native or 'NONE — the freeze omitted it'}")

        features = rows(database, "SELECT `Feature` FROM `Feature`", 1)
        print(f"features: {[f[0] for f in features]}")
    finally:
        database.Close()

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("RESULT: OK — dialog cycles valid, version current, native module bundled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
