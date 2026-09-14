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
import importlib
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

#: Where ``build_ext`` is told to write, so the build can install a single
#: known file into ``src/`` instead of hunting for whatever setuptools
#: decided to name it. Emptied before every build, which is what makes the
#: contents unambiguous.
STAGING_DIR: Path = EDITOR_ROOT / "build" / "native-lib"

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


def _extension_class():
    """Return the ``Extension`` class this environment's build command accepts.

    Not a fixed choice, because the answer depends on import order in a way
    setuptools does not guarantee:

    * ``setuptools.Extension`` is the documented public class. Once
      :func:`_prepare_setuptools` has unified the ``distutils`` shim it *is*
      a subclass of the class the build command validates against, and the
      check passes;
    * before that unification the two are unrelated classes — same file,
      imported twice under different names — and the public class is
      rejected with "'ext_modules' option must be a list of Extension
      instances", which names the wrong problem entirely.

    So the class is read out of the validation function's own globals. A
    function cannot disagree with itself about which class it is about to
    test against.
    """
    _prepare_setuptools()

    try:
        from setuptools.command.build_ext import build_ext
    except ImportError:
        from setuptools._distutils.command.build_ext import build_ext

    validator = getattr(build_ext, "check_extensions_list", None)
    if validator is not None:
        candidate = validator.__globals__.get("Extension")
        if candidate is not None:
            return candidate

    from setuptools import Extension

    return Extension


def _prepare_setuptools() -> None:
    """Make setuptools able to build anything in the presence of cx_Freeze.

    Constructing a ``setuptools.Distribution`` makes setuptools load its
    ``setuptools.finalize_distribution_options`` entry points. On a machine
    with cx_Freeze installed, one of those entry points imports
    ``cx_Freeze``, whose ``setuptools.command.install`` shim does
    ``import distutils.command.install as orig``. Under setuptools'
    distutils shim that resolves to
    ``setuptools._distutils.command.install`` — a submodule setuptools never
    imports eagerly — so the name lookup fails and *every* distribution
    construction raises, including this one, with an error about
    ``aphelion_native`` that has nothing to do with ``aphelion_native``.

    Importing that submodule up front populates it, and the plugin then
    loads. Done defensively: on an environment without cx_Freeze, or with a
    setuptools/cx_Freeze pairing that is not broken, this is a no-op.
    """
    try:
        import setuptools  # noqa: F401
    except ImportError:
        return

    for name in (
        "setuptools._distutils.command.install",
        "setuptools._distutils.extension",
    ):
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - a best-effort compatibility shim
            continue


def _extension():
    """Return a configured ``Extension`` for the kernels."""
    return _extension_class()(
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


def _search_roots() -> list[Path]:
    """Directories that could hold the extension after a build."""
    return [
        SRC_DIR,
        EDITOR_ROOT,
        NATIVE_DIR,
        STAGING_DIR,
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


def _import_from_src(module_name: str):
    """Import ``module_name`` as if ``src/`` were on ``sys.path``.

    The build script is run from the editor directory, where ``src/`` is not
    importable, so ``importlib.find_spec`` cannot see a module that is
    sitting exactly where it belongs. Reporting "built but not importable"
    for a perfectly good build sent the reader hunting for a path problem
    that did not exist. Adding the directory for the duration of the check
    makes the question being asked — *does this artifact actually load?* —
    answerable.
    """
    directory = str(SRC_DIR)
    inserted = directory not in sys.path
    if inserted:
        sys.path.insert(0, directory)

    importlib.invalidate_caches()

    return inserted, directory


def is_built() -> bool:
    """Return whether the extension is present in ``src/`` and importable."""
    if not INSTALL_PATH.exists() and not built_modules(SRC_DIR):
        return False

    inserted, directory = _import_from_src(MODULE_NAME)
    try:
        return importlib.util.find_spec(MODULE_NAME) is not None
    finally:
        if inserted and directory in sys.path:
            sys.path.remove(directory)


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

    # Build into a staging directory this script owns, then install the one
    # file that appears in it. Three things this buys, all of which were
    # broken by the obvious alternative:
    #
    # 1. ``--inplace`` derives its destination from the extension's
    #    *package*, and this extension is a bare top-level module with no
    #    package, so setuptools fell back to ``build/lib.<platform>-<abi>/``
    #    and ``--inplace`` silently did nothing. ``package_dir`` did not fix
    #    it either.
    # 2. ``--build-lib src`` put the module in the right directory but under
    #    its ABI-tagged name, leaving ``aphelion_native.pyd`` — the name the
    #    installer and ``import aphelion_native`` both need — absent.
    # 3. Pinning the name with a ``cmdclass`` override made setuptools load
    #    its ``setup_keywords`` entry points, which imports cx_Freeze's
    #    plugin and fails against setuptools 84.
    #
    # An empty staging directory is unambiguous: whatever lands in it is the
    # output of this run, with no mtime guessing and no ABI-tag matching.
    staging = STAGING_DIR
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

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
        str(staging),
        "--force",
    ]
    if not verbose:
        distribution.script_args.append("--quiet")

    try:
        # Two calls, and both are required. ``parse_command_line`` only
        # *parses* — it records ``build_ext`` in ``distribution.commands``
        # and returns — so on its own it links nothing while reporting no
        # error at all, which is why the build looked successful and
        # produced no module. ``run_commands`` is what actually compiles.
        distribution.parse_command_line()
        distribution.run_commands()
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

    produced = built_modules(staging)

    # Anything setuptools staged somewhere else anyway is still ours.
    if not produced:
        produced = _relocate_into_src(verbose=verbose) or built_modules(SRC_DIR)

    if not produced:
        _report_missing_artifact()
        return 1

    installed = _install_artifact(produced, verbose=verbose)
    if installed is None:
        _report_missing_artifact()
        return 1

    print(f"built {installed}")
    return 0


def _install_artifact(produced: "list[Path]", *, verbose: bool = True) -> Path | None:
    """Install the freshly built module as ``src/aphelion_native.pyd``.

    Every other ``aphelion_native*`` module in ``src/`` is removed as it
    goes. A stale copy under an ABI-tagged name is not merely untidy: it is
    a module for a different interpreter sitting on the import path, and
    ``import aphelion_native`` prefers whichever it finds first.

    Returns:
        The installed module, or ``None`` if it could not be put in place.
    """
    newest = max(produced, key=lambda path: path.stat().st_mtime_ns)

    for stale in built_modules(SRC_DIR):
        if stale == INSTALL_PATH:
            continue
        try:
            stale.unlink()
            if verbose:
                print(f"removed stale {stale.name}")
        except OSError:
            continue

    if newest == INSTALL_PATH:
        return INSTALL_PATH

    try:
        if INSTALL_PATH.exists():
            INSTALL_PATH.unlink()
        shutil.move(str(newest), str(INSTALL_PATH))
    except OSError as exc:
        print(f"error: could not install {newest.name}: {exc}", file=sys.stderr)
        return None

    if verbose:
        print(f"installed {INSTALL_PATH.name}")
    return INSTALL_PATH


def _report_missing_artifact() -> None:
    """Explain a build that produced no module, naming where it looked.

    "reported success but no artifact was found" is the message that cost
    the most time to diagnose, because a successful compile in the wrong
    directory is invisible from it.
    """
    print(
        f"error: the build produced no extension artifact for {SRC_DIR}",
        file=sys.stderr,
    )
    strays = list(_iter_stray_modules())
    if strays:
        print(f"       found elsewhere: {strays[0]}", file=sys.stderr)
        print(
            "       re-run: python native/build.py   # installs it into src/",
            file=sys.stderr,
        )
    else:
        print(
            "       the compiler produced nothing; check the output above "
            "for the first error",
            file=sys.stderr,
        )


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

    inserted, directory = _import_from_src(MODULE_NAME)
    try:
        if importlib.util.find_spec(MODULE_NAME) is None:
            print(f"present at {artifacts[0]} but not importable; check sys.path")
            print("fallbacks: active")
            return 1

        try:
            import aphelion_native  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            print(f"import failed: {exc}")
            note = _abi_note(artifacts[0])
            if note:
                print(note)
            print("fallbacks: active")
            return 1

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
    finally:
        if inserted and directory in sys.path:
            sys.path.remove(directory)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch."""
    parser = argparse.ArgumentParser(
        prog="python native/build.py",
        description="Build the aphelion_native extension into src/.",
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
