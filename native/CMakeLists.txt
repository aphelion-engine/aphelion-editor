# CMake build for the optional aphelion_native extension.
#
# The primary build path is `python native/build.py`, which uses setuptools
# and needs nothing beyond the Python headers. This CMake project exists for
# the cases setuptools does not cover well:
#
#   * building as part of a larger native build or IDE (CLion, Visual Studio)
#   * inspecting warnings the setuptools driver hides
#   * producing a deliberately optimised or instrumented build
#
# Both paths produce the same module and are interchangeable.
#
# Usage:
#   cmake -S native -B native/build -DPython_EXECUTABLE=path/to/python
#   cmake --build native/build --config Release
#   cmake --install native/build   # installs into the interpreter's site-packages

cmake_minimum_required(VERSION 3.20)
project(aphelion_native LANGUAGES C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Locate the interpreter so we build against the exact headers the editor
# will load the module into. Building against a different minor version
# produces a module that refuses to import, which is a confusing failure to
# debug — so require it explicitly rather than falling back globally.
if(NOT DEFINED Python_EXECUTABLE)
    find_package(Python 3.9 REQUIRED COMPONENTS Interpreter Development.Module)
else()
    find_package(Python 3.9 REQUIRED COMPONENTS Interpreter Development.Module)
endif()

message(STATUS "aphelion_native: building against Python ${Python_VERSION}")

add_library(aphelion_native MODULE aphelion_native.c)

target_include_directories(aphelion_native PRIVATE ${Python_INCLUDE_DIRS})

# A MODULE library is a plugin: no "lib" prefix, matching the name CPython
# expects for the import to resolve.
set_target_properties(aphelion_native PROPERTIES
    PREFIX ""
    OUTPUT_NAME "aphelion_native"
)

if(MSVC)
    # /O2 is MSVC's "optimise for speed". The kernels are memory-bound
    # straight-line loops, so this is sufficient; /arch:AVX2 is deliberately
    # NOT used, because a module that refuses to load on an older CPU is a
    # worse outcome than a kernel that is a few percent slower.
    target_compile_options(aphelion_native PRIVATE /O2 /W3)
    target_compile_definitions(aphelion_native PRIVATE _CRT_SECURE_NO_WARNINGS)
else()
    target_compile_options(aphelion_native PRIVATE
        -O2
        -Wall
        -Wextra
        -Wno-unused-parameter
    )
endif()

if(APPLE)
    # Undefined dynamic lookup is required for extension modules on macOS.
    target_link_options(aphelion_native PRIVATE "-undefined" "dynamic_lookup")
endif()

# Install into the interpreter's site-packages so `import aphelion_native`
# resolves without manipulating sys.path.
include(GNUInstallDirs)
execute_process(
    COMMAND "${Python_EXECUTABLE}" -c
            "import sysconfig; print(sysconfig.get_paths()['platlib'])"
    OUTPUT_VARIABLE APHELION_SITE_PACKAGES
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
install(TARGETS aphelion_native LIBRARY DESTINATION "${APHELION_SITE_PACKAGES}")
