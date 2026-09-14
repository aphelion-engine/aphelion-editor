"""Exercise the MSI dialog-cycle validator, including its rejection cases.

``verify_msi.py`` checks a built artifact. This checks the *validator* that
decides whether a dialog is well-formed, plus the Control table the generator
produces before any repair runs.

The negative cases are the point. A validator that accepts everything passes
``verify_msi.py`` on a good MSI and on a broken one alike.

The repair pass itself (``_repair_dialog_control_cycles``) is not exercised
here: it takes a live MSI database and issues ``UPDATE`` statements against it,
so it has no useful isolated form. It is covered end-to-end by ``verify_msi.py``,
which asserts that every dialog in the finished package is a single cycle.

Usage::

    python scripts/check_msi_cycles.py
"""

from __future__ import annotations

import sys
from pathlib import Path

EDITOR_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EDITOR_ROOT / "src"))

from aphelion_build import (  # noqa: E402
    DIRECTORY_DIALOG,
    OPTIONS_DIALOG,
    _control_cycle_order,
    _options_controls,
    msi_table_data,
)

# Column order in the Control rows produced by msi_table_data, which is also the
# order aphelion_build reads them in.
DIALOG_COL, CONTROL_COL, NEXT_COL, X_COL, Y_COL = 0, 1, 10, 3, 4

failures: list[str] = []


def expect_valid(label: str, controls: list[tuple[str, str, int, int]]) -> list[str] | None:
    order = _control_cycle_order(controls)
    if order is None:
        failures.append(f"{label}: expected a valid cycle, got None")
        print(f"  FAIL {label}: expected a valid cycle")
    else:
        print(f"  OK   {label}: {len(order)} controls, single cycle")
    return order


def expect_invalid(label: str, controls: list[tuple[str, str, int, int]]) -> None:
    order = _control_cycle_order(controls)
    if order is not None:
        failures.append(f"{label}: accepted an invalid chain ({order})")
        print(f"  FAIL {label}: should have been rejected, got {order}")
    else:
        print(f"  OK   {label}: rejected")


print("=== the OptionsDlg table the build actually generates ===")
controls = [
    (row[CONTROL_COL], row[NEXT_COL] or "", int(row[X_COL]), int(row[Y_COL]))
    for row in _options_controls()
    if row[DIALOG_COL] == OPTIONS_DIALOG
]
order = expect_valid("OptionsDlg", controls)
if order:
    print("       " + " -> ".join(order) + " -> " + order[0])

print("\n=== rejection cases ===")
# Two controls naming the same successor. This was OptionsDlg: both Description
# and ScopeLabel pointed at InstallScope.
expect_invalid(
    "duplicate successor",
    [("A", "C", 0, 0), ("B", "C", 0, 20), ("C", "A", 0, 40)],
)
# An inner loop that closes before covering the dialog. This was the
# Next -> Cancel -> Back -> Next sub-loop.
expect_invalid(
    "early-closing sub-loop",
    [("A", "B", 0, 0), ("B", "A", 0, 20), ("C", "A", 0, 40)],
)
# A pointer to a control that is not on the dialog.
expect_invalid(
    "dangling successor",
    [("A", "B", 0, 0), ("B", "Ghost", 0, 20)],
)

print("\n=== the Control table the build generates ===")
tables = msi_table_data(
    product_name="Aphelion Editor",
    start_menu_dir="ProgramMenuFolder",
    user_target_dir=r"[LocalAppDataFolder]Aphelion\Aphelion Editor",
    machine_target_dir=r"[ProgramFiles64Folder]Aphelion\Aphelion Editor",
)
control_rows = tables.get("Control", [])
print(f"  {len(tables)} tables, {len(control_rows)} control rows")
if not control_rows:
    failures.append("msi_table_data produced no Control rows")

dialogs: dict[str, list[tuple[str, str, int, int]]] = {}
for row in control_rows:
    dialogs.setdefault(row[DIALOG_COL], []).append(
        (row[CONTROL_COL], row[NEXT_COL] or "", int(row[X_COL]), int(row[Y_COL]))
    )

# Dialogs the generator leaves broken are expected — _repair_dialog_control_cycles
# runs immediately afterwards in the real build. What matters is that the repair
# has something well-defined to act on: every dialog either validates, or is one
# the validator can positively identify as broken.
broken = [name for name in sorted(dialogs) if _control_cycle_order(dialogs[name]) is None]
print(f"  {len(dialogs)} dialogs; {len(broken)} need the repair pass: {broken or 'none'}")

# The DirectoryDlg collision is a deliberate, known shape: extra labels are added
# to a dialog whose chain already names their successors. If it ever stops being
# broken, the repair pass is dead code and should be re-examined rather than
# quietly left in the build.
if DIRECTORY_DIALOG in broken:
    print("  OK   DirectoryDlg is broken as generated, so the repair pass is exercised")
else:
    print(
        f"  NOTE {DIRECTORY_DIALOG} already validates — the repair pass may be redundant"
    )

print()
if failures:
    print(f"RESULT: FAIL ({len(failures)})")
    for failure in failures:
        print(f"  - {failure}")
    raise SystemExit(1)
print("RESULT: OK — the validator accepts valid chains and rejects broken ones")
