"""Run a diagnostic module under export-style limits and a wall-time deadline.

Example: python -m tools.bounded_run --seconds 120 tools.effects_benchmark --output results.json
"""
import argparse
import os
import subprocess
import sys

from render.process_limits import ExportProcessLimits
from render.resource_limits import MIB, available_export_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--memory-mib', type=int, default=2048)
    parser.add_argument('--cpu-percent', type=int, default=25)
    parser.add_argument('module')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    budget = available_export_bytes(max(1, args.memory_mib) * MIB)
    if budget < 512 * MIB:
        raise RuntimeError('Not enough free memory for a bounded diagnostic')
    environment = os.environ.copy()
    environment.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                       QT_QPA_PLATFORM='offscreen')
    bootstrap = "import sys,runpy; input(); module=sys.argv.pop(1); runpy.run_module(module,run_name='__main__')"
    process = subprocess.Popen([sys.executable, '-c', bootstrap, args.module, *args.arguments],
                               stdin=subprocess.PIPE, env=environment)
    limits = None
    try:
        limits = ExportProcessLimits(process.pid, budget, args.cpu_percent)
        print(f'Diagnostic limits: {budget // MIB} MiB, {args.cpu_percent}% CPU, {args.seconds}s', flush=True)
        process.stdin.write(b'RUN\n')
        process.stdin.close()
        return process.wait(timeout=max(1, args.seconds))
    finally:
        if limits:
            limits.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


if __name__ == '__main__':
    raise SystemExit(main())
