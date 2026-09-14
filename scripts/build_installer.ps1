# Build the Aphelion Editor Windows installer.
#
# The editor directory must be the working directory: cx_Freeze and setuptools
# both write relative outputs and the packaging entry point resolves its own
# paths from there, so this script changes into it rather than assuming the
# caller is already there.
#
#   pwsh -File scripts\build_installer.ps1
#   pwsh -File scripts\build_installer.ps1 -BuildDir ..\releases_check
#
# Afterwards, verify the result — a produced .msi is not evidence that the
# installer works:
#
#   python scripts\verify_msi.py
#
# Note: do not interrupt a cx_Freeze build. Killing it mid-flight leaves a
# directory lock behind and the next run fails with "the build_exe directory
# cannot be cleaned".
[CmdletBinding()]
param(
    # Where the .msi is written. Defaults to releases/ next to the project root.
    [string]$BuildDir,

    # Extra arguments forwarded to `python -m aphelion_build`.
    [string[]]$ExtraArgs
)

$ErrorActionPreference = 'Stop'

$editorRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $editorRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    throw "No virtual environment at $python. Create one and install the freeze extras first."
}

if (-not $BuildDir) {
    $BuildDir = Join-Path $editorRoot 'releases'
}

Push-Location $editorRoot
try {
    $env:PYTHONPATH = 'src'
    Write-Host "Building the installer into $BuildDir" -ForegroundColor Cyan
    & $python -m aphelion_build --installer --build-dir $BuildDir @ExtraArgs
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($code -ne 0) {
    Write-Host "Build failed with exit code $code" -ForegroundColor Red
    exit $code
}

Write-Host ''
Write-Host 'Build finished. Verify the package before shipping it:' -ForegroundColor Cyan
Write-Host "  & '$python' `"$PSScriptRoot\verify_msi.py`""
exit 0
