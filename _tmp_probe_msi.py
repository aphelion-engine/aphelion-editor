"""Throwaway probe: inspect the File/Directory tables of the installer."""

from __future__ import annotations

import sys
from pathlib import Path

from msilib import MSIDBOPEN_READONLY, OpenDatabase


def _rows(db: object, sql: str, columns: int = 4) -> list[tuple[str, ...]]:
    view = db.OpenView(sql)  # type: ignore[attr-defined]
    view.Execute(None)
    out: list[tuple[str, ...]] = []
    while True:
        record = view.Fetch()
        if record is None:
            break
        values: list[str] = []
        for index in range(1, columns + 1):
            try:
                values.append(str(record.GetString(index)))
            except Exception:
                values.append("")
        out.append(tuple(values))
    view.Close()
    return out


def main() -> int:
    msi = Path("releases/AphelionEditorSetup-0.1.0-win64.msi").resolve()
    db = OpenDatabase(str(msi), MSIDBOPEN_READONLY)

    files = _rows(db, "SELECT `File`, `Component_`, `FileName` FROM `File`", 3)
    print("sample file names:")
    for row in files[:8]:
        print(f"  {row[0]} | {row[1]} | {row[2]}")

    dirs = _rows(
        db, "SELECT `Directory`, `Directory_Parent`, `DefaultDir` FROM `Directory`", 3
    )
    print(f"\ndirectory rows: {len(dirs)}")
    for row in dirs:
        if any(
            token in (row[0] + row[2]).lower()
            for token in ("userdata", "log", "plugin", "sdk")
        ):
            print(f"  {row[0]} | {row[1]} | {row[2]}")

    wanted = {
        row[0]
        for row in dirs
        if any(token in (row[0] + row[2]).lower() for token in ("userdata", "log"))
    }
    print(f"\nmatching directory ids: {sorted(wanted)}")
    components = _rows(db, "SELECT `Component`, `Directory_` FROM `Component`", 2)
    by_component = {row[0]: row[1] for row in components}
    matched = [row for row in components if row[1] in wanted]
    print(f"components in those dirs: {len(matched)}")
    for row in files:
        if by_component.get(row[1]) in wanted:
            print(f"  {by_component.get(row[1])}: {row[0]} | {row[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
