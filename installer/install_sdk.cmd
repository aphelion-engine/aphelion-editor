@echo off
setlocal EnableExtensions
set "WHEEL="
for %%F in ("%~dp0sdk\aphelion_sdk-*.whl") do set "WHEEL=%%~fF"
if not defined WHEEL exit /b 0
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 -m pip install --upgrade --user "%WHEEL%"
  if %ERRORLEVEL%==0 exit /b 0
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python -m pip install --upgrade --user "%WHEEL%"
  if %ERRORLEVEL%==0 exit /b 0
)
exit /b 0
