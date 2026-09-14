"""Why does build_ext produce nothing? Inspect the command object."""

from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "nb", str(Path(__file__).resolve().parent / "native" / "build.py")
)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

from setuptools import Distribution  # noqa: E402

distribution = Distribution(
    {"name": "aphelion-native", "version": "1.0.0", "ext_modules": [module._extension()]}
)
distribution.script_args = [
    "build_ext",
    "--build-lib",
    str(module.SRC_DIR),
    "--force",
]

print("src dir          :", module.SRC_DIR)
print("before parse     :", module.built_modules(module.SRC_DIR))

distribution.parse_command_line()
print("commands         :", getattr(distribution, "commands", None))
print("after parse      :", module.built_modules(module.SRC_DIR))

command = distribution.get_command_obj("build_ext")
print("build_lib        :", command.build_lib)
print("build_temp       :", command.build_temp)
print("force            :", command.force)
print("inplace          :", command.inplace)
print("ext_fullpath     :", command.get_ext_fullpath(module.MODULE_NAME))
print("outputs          :", [str(path) for path in command.get_outputs()])

distribution.run_commands()
print("after run_commands:", module.built_modules(module.SRC_DIR))
strays = list(module._iter_stray_modules())
print("strays           :", [str(path) for path in strays])
