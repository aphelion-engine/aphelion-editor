import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
import platform
import shutil

@dataclass
class ProcessResult:
    return_code: int
    stdout: str
    stderr: str


def run(script_path: str, *args: str) -> ProcessResult:
    path = Path(script_path)
    if not path.exists() or not path.is_file():
        print(f"Error: {script_path} is not a valid file")
        return 1
    ext = path.suffix.lower()
    system_os = platform.system()
    if ext in [".sh", ".bash"]:
        interpreter = shutil.which("bash") or shutil.which("sh")
        if not interpreter:
            raise EnvironmentError("No bash/sh interpreter found on this system")
        cmd = [interpreter, str(script_path), *args]
    elif ext == ".ps1":
        if system_os == "Windows":
            interpreter = shutil.which("powershell") or shutil.which("pwsh")
            if not interpreter:
                raise EnvironmentError("PowerShell not found on this system.")
            cmd = [interpreter, "-ExecutionPolicy", "Bypass", "-File", str(path), *args]
    else:
        raise ValueError(f"Unsupported script file extension: {ext}")
            
    try:
        subprocess_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )
        return ProcessResult(
            return_code=subprocess_result.returncode,
            stdout=subprocess_result.stdout,
            stderr=subprocess_result.stderr
        )
    except Exception as e:  # noqa: BLE001
        return ProcessResult(
            return_code=1,
            stdout="",
            stderr=str(e)
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a script")
    parser.add_argument("filepath", type=str, help="The path to the script to run")
    parser.add_argument("args", nargs="*", help="The arguments to pass to the script")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show verbose output")
    args = parser.parse_args()
    result = run(args.filepath, *args.args)
    if args.verbose:
        print(f"Return code: {result.return_code}")
        print(f"Stdout: {result.stdout}")
        print(f"Stderr: {result.stderr}")
    else:
        print(result.stdout)
    if result.return_code != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        sys.exit(result.return_code)
