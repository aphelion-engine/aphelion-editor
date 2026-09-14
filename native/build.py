"""Build the ``aphelion_native`` extension in place.

Usage::

    python native/build.py            # build (or rebuild) the extension
    python native/build.py --check    # report whether it is importable
    python native/build.py --clean    # remove build artefacts

This script is usually not run by hand. The editor's boot pipeline calls
``core.native.ensure_available()``, which loads this module and compiles the
extension on a background thread whenever it is missing — so a developer
clone or a fresh checkout acquires the native kernels without anyone
remembering to run a command.

That makes the extension *automatic*, not *mandatory*. Nothing imports it as
a hard dependency: ``core.native`` probes for it and every kernel has a
verified NumPy/OpenCV reference implementation. A machine without a C
compiler still runs the editor, and a failed build can never turn into a
broken install — the reason is reported in Preferences → Performance rather
than being swallowed.

A separate build script (rather than adding the extension to the project's
``setup.py``) keeps the cx_Freeze packaging flow — which builds a frozen
tree, not wheels — working exactly as before while still giving developers
and release builds a one-command path to the native core.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path

NATIVE_DIR = Path(__file__).resolve().parent
EDITOR_ROOT = NATIVE_DIR.parent
SRC_DIR = EDITOR_ROOT / "src"
SOURCE = NATIVE_DIR / "aphelion_native.c"
MODULE_NAME = "aphelion_native"

#: The name the extension is *installed* under, without the ABI tag.
#:
#: CPython accepts an untagged extension — ``.pyd`` is the last entry in
#: ``importlib.machinery.EXTENSION_SUFFIXES`` on Windows, and a bare ``.so``
#: works on POSIX — so ``aphelion_native.pyd`` imports exactly like
#: ``aphelion_native.cp314-win_amd64.pyd`` does.
#:
#: The trade-off is that an untagged name does not announce which
#: interpreter built it, so a module left over from a different Python is
#: found and then fails to import. That failure is loud rather than silent:
#: ``core.native.probe`` reports the module as unusable and the boot stage
#: rebuilds it, and :func:`check` names the mismatched ABI explicitly.
PLAIN_SUFFIX: str = ".pyd" if sys.platform == "win32" else ".so"

#: Where the finished module must end up.
INSTALL_PATH: Path = SRC_DIR / f"{MODULE_NAME}{PLAIN_SUFFIX}"

#: Optimisation flags. The kernels are memory-bound loops written to be
#: auto-vectorised; -O2 is already sufficient and -O3 is not worth the
#: extra build time or the risk of aggressive vectorisation changing
#: floating-point behaviour. ``/O2`` is MSVC's equivalent.
_EXTRA_COMPILE_ARGS = {
    "msvc": ["/O2"],
    "unix": ["-O2", "-std=c99"],
}


def _compiler_family() -> str:
    """Return ``"msvc"`` or ``"unix"`` for this platform's default compiler."""
    return "msvc" if sys.platform == "win32" else "unix"


def _extension():
    """Return a configured ``setuptools.Extension``."""
    from setuptools import Extension

    return Extension(
        MODULE_NAME,
        sources=[str(SOURCE)],
        include_dirs=[],
        extra_compile_args=_EXTRA_COMPILE_ARGS[_compiler_family()],
    )


def built_modules(directory: Path) -> list[Path]:
    """Return every built extension artifact in ``directory``.

    Matches both the untagged name the build installs under and the
    ABI-tagged name setuptools produces before it is renamed, because a
    check that recognises only one of the two reports a successful build as
    a failure — which is what happened when the build wrote
    ``aphelion_native.cp314-win_amd64.pyd`` and the check looked only for
    ``aphelion_native.pyd``.
    """
    found: list[Path] = []
    for suffix in set(EXTENSION_SUFFIXES) | {".pyd", ".so", ".dylib"}:
        found.extend(directory.glob(f"{MODULE_NAME}*{suffix}"))
    # De-duplicate while keeping a stable order.
    return sorted({path.resolve() for path in found})


def _rename_to_plain(verbose: bool = True) -> Path | None:
    """Rename the freshly built module in ``src/`` to its untagged name.

    The compiled module is the only artifact that matters, so a stale copy
    under a different ABI tag is removed rather than left to shadow it.

    Returns:
        The installed module, or ``None`` when nothing was built.
    """
    artifacts = built_modules(SRC_DIR)
    if not artifacts:
        return None

    # The most recently written file is the one this build just produced;
    # mtime is the only signal available once the ABI tag is discarded.
    newest = max(artifacts, key=lambda path: path.stat().st_mtime_ns)

    for artifact in artifacts:
        if artifact in (newest, INSTALL_PATH):
            continue
        try:
            artifact.unlink()
            if verbose:
                print(f"removed stale {artifact.name}")
        except OSError:
            continue

    if newest == INSTALL_PATH:
        return newest

    try:
        if INSTALL_PATH.exists():
            INSTALL_PATH.unlink()
        newest.replace(INSTALL_PATH)
    except OSError as exc:
        if verbose:
            print(f"warning: could not rename {newest.name}: {exc}")
        return newest

    if verbose:
        print(f"installed {INSTALL_PATH.name}")
    return INSTALL_PATH


def _search_roots() -> list[Path]:
    """Directories that could hold the extension after a build."""
    return [
        SRC_DIR,
        EDITOR_ROOT,
        NATIVE_DIR,
        EDITOR_ROOT / "build",
        NATIVE_DIR / "build",
    ]


def _iter_stray_modules():
    """Yield every built extension outside ``src/``, anywhere below the roots.

    Recursive on purpose. When ``--inplace`` does not take effect (it
    resolves its destination from the extension's *package*, and a bare
    top-level module has none), ``build_ext`` stages the module in
    ``build/lib.<platform>-<abi>/``. A sweep that only looked at the top
    level of ``build/`` found nothing there, so a build that had in fact
    succeeded was reported as having produced no artifact — and the module
    was left in the staging directory where nothing imports it.
    """
    seen: set[Path] = set()
    source_dir = SRC_DIR.resolve()

    for root in _search_roots():
        if not root.is_dir():
            continue
        for suffix in set(EXTENSION_SUFFIXES) | {".pyd", ".so", ".dylib"}:
            for path in root.rglob(f"{MODULE_NAME}*{suffix}"):
                resolved = path.resolve()
                # Artifacts already in place, and the compiled object files
                # under the temp tree, are not strays.
                if resolved in seen or resolved.parent == source_dir:
                    continue
                seen.add(resolved)
                yield resolved


def module_path() -> Path:
    """Return the installed location of the extension.

    Prefers the canonical installed name, then any artifact that actually
    exists, and otherwise reports where the build will put it.
    """
    if INSTALL_PATH.exists():
        return INSTALL_PATH

    existing = built_modules(SRC_DIR)
    if existing:
        return existing[0]

    return INSTALL_PATH


def is_built() -> bool:
    """Return whether the extension appears to be present and importable."""
    if not built_modules(SRC_DIR):
        return False
    return importlib.util.find_spec(MODULE_NAME) is not None


def _relocate_into_src(verbose: bool = True) -> list[Path]:
    """Move any stray build output into ``src/``.

    A safety net, not the primary mechanism: :func:`build` now hands
    setuptools an explicit ``--build-lib`` so the module is written straight
    into ``src/``. This catches the case where a setuptools version ignores
    that and stages the module somewhere else anyway.
    """
    moved: list[Path] = []

    for candidate in _iter_stray_modules():
        destination = SRC_DIR / candidate.name
        try:
            if destination.exists():
                destination.unlink()
            shutil.move(str(candidate), str(destination))
        except OSError as exc:
            if verbose:
                print(f"warning: could not move {candidate}: {exc}")
            continue
        moved.append(destination)
        if verbose:
            print(f"moved {candidate.name} -> src/")

    return moved


def build(verbose: bool = True) -> int:
    """Compile the extension into ``src/``.

    Returns:
        Process exit code; ``0`` on success.
    """
    if not SOURCE.is_file():
        print(f"error: source not found: {SOURCE}", file=sys.stderr)
        return 1

    try:
        from setuptools import Distribution
    except ImportError:
        print(
            "error: setuptools is required to build the native extension.\n"
            "       pip install setuptools",
            file=sys.stderr,
        )
        return 1

    SRC_DIR.mkdir(parents=True, exist_ok=True)

    # The destination is stated explicitly instead of left to ``--inplace``.
    #
    # ``--inplace`` derives where to put the module from the extension's
    # *package*, and this extension is a bare top-level module with no
    # package — so setuptools falls back to its normal staging directory,
    # ``build/lib.<platform>-<abi>/``, and ``--inplace`` silently does
    # nothing. ``package_dir`` was an attempt to steer that and does not
    # reliably do so either: the module still ended up in the staging tree,
    # where ``import aphelion_native`` can never find it.
    #
    # ``--build-lib`` is not a hint, it is the output path, so the compiled
    # module lands beside the source tree the application actually imports
    # from. ``_relocate_into_src`` remains as a safety net.
    distribution = Distribution(
        {
            "name": "aphelion-native",
            "version": "1.0.0",
            "ext_modules": [_extension()],
        }
    )
    distribution.script_args = [
        "build_ext",
        "--build-lib",
        str(SRC_DIR),
        "--force",
    ]
    if not verbose:
        distribution.script_args.append("--quiet")

    try:
        # ``parse_command_line`` executes the requested command; it must not
        # be run a second time by hand or the extension is built twice.
        distribution.parse_command_line()
    except Exception as exc:  # noqa: BLE001 - a build failure is not fatal
        print(f"error: native build failed: {exc}", file=sys.stderr)
        print(
            "hint: install a C compiler (Visual Studio Build Tools on Windows,\n"
            "      build-essential + python3-dev on Linux, Xcode Command Line\n"
            "      Tools on macOS).\n"
            "      The editor runs without it using the Python fallbacks.",
            file=sys.stderr,
        )
        return 1

    _relocate_into_src(verbose=verbose)

    installed = _rename_to_plain(verbose=verbose)

    artifacts = built_modules(SRC_DIR)
    if not artifacts or installed is None:
        # Say where the module *did* end up rather than only that it is
        # missing: the whole failure mode here was a successful compile in
        # the wrong directory, which is invisible from the error alone.
        strays = list(_iter_stray_modules())
        print(
            "error: the build reported success but no extension artifact "
            f"was found in {SRC_DIR}",
            file=sys.stderr,
        )
        if strays:
            print(f"       found elsewhere: {strays[0]}", file=sys.stderr)
            print(
                "       re-run: python native/build.py   # moves it into src/",
                file=sys.stderr,
            )
        return 1

    for artifact in artifacts:
        print(f"built {artifact}")
    return 0


def clean() -> int:
    """Remove build artefacts (the compiled module and setuptools caches)."""
    removed = 0

    directories = [
        NATIVE_DIR / "build",
        EDITOR_ROOT / "build" / "temp",
    ]
    for directory in directories:
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
            removed += 1

    # Sweep every location a build might have written to. Recursive, because
    # a build whose output path was not honoured stages the module in
    # ``build/lib.<platform>-<abi>/`` — leaving a stray copy that a later
    # import could pick up instead of the real one.
    for artifact in _iter_stray_modules():
        try:
            artifact.unlink()
            removed += 1
        except OSError:
            continue

    for artifact in built_modules(SRC_DIR):
        try:
            artifact.unlink()
            removed += 1
        except OSError:
            continue

    print(f"removed {removed} artefact(s)")
    return 0


def _abi_note(artifact: Path) -> str:
    """Explain an import failure caused by a stale interpreter ABI.

    The installed name is deliberately untagged, so a module left over from
    a different Python is *found* and then refuses to load. That is the one
    real cost of the plain name, and it deserves a better diagnostic than
    "not importable, check sys.path" — which sends the reader looking for a
    path problem that does not exist.
    """
    expected = EXTENSION_SUFFIXES[0] if EXTENSION_SUFFIXES else ""
    if not expected or artifact.name != INSTALL_PATH.name:
        return ""
    return (
        f"       note: {artifact.name} is untagged, so it does not record"
        f" which interpreter built it.\n"
        f"       this interpreter expects {expected} — rebuild to be sure:\n"
        f"       python native/build.py"
    )


def check() -> int:
    """Report whether the extension is built and importable."""
    artifacts = built_modules(SRC_DIR)

    if not artifacts:
        stray = list(_iter_stray_modules())
        if stray:
            print(f"not in src/ (found elsewhere: {stray[0]})")
            print("run: python native/build.py    # to move it into place")
        else:
            print(f"not built (expected {INSTALL_PATH.name} in {SRC_DIR})")
        print("fallbacks: active (NumPy/OpenCV reference implementations)")
        return 1

    spec = importlib.util.find_spec(MODULE_NAME)
    if spec is None:
        print(f"present at {artifacts[0]} but not importable; check sys.path")
        print("fallbacks: active")
        return 1

    try:
        import aphelion_native  # type: ignore[import-not-found]

        version = getattr(aphelion_native, "APHELION_NATIVE_VERSION", 0)
        kernels_found = sorted(
            name
            for name in ("swap_bgr_rgb_inplace", "resize_bgr_to_rgb", "rgb_to_luma")
            if hasattr(aphelion_native, name)
        )
        print(f"built and importable: {artifacts[0]}")
        print(f"version : {version}")
        print(f"kernels : {', '.join(kernels_found) or 'none'}")
        print(f"pool    : {'yes' if hasattr(aphelion_native, 'Pool') else 'no'}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"import failed: {exc}")
        note = _abi_note(artifacts[0])
        if note:
            print(note)
        print("fallbacks: active")
        return 1


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch."""
    parser = argparse.ArgumentParser(
        prog="python native/build.py",
        description="Build the optional aphelion_native extension.",
    )
    parser.add_argument("--check", action="store_true", help="Report build status.")
    parser.add_argument("--clean", action="store_true", help="Remove artefacts.")
    parser.add_argument("--quiet", action="store_true", help="Suppress compiler output.")
    args = parser.parse_args(argv)

    if args.check:
        return check()
    if args.clean:
        return clean()

    exit_code = build(verbose=not args.quiet)
    if exit_code != 0:
        return exit_code

    # Verify the module actually imports. A successful compile proves the C
    # is valid; it does not prove the artifact is loadable by *this*
    # interpreter, and an ABI mismatch between the compiler's Python headers
    # and the running interpreter is exactly the failure worth catching here
    # rather than three steps later inside a frame decode.
    print()
    if check() != 0:
        print(
            "\nwarning: the extension built but could not be imported.\n"
            "         The editor will keep using the Python fallbacks.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
