"""Windowless scheduled entrypoint preserving the deployed runtime configuration."""
from pathlib import Path
import argparse
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--script',default=r'scripts\run_daily_drive.py',
        choices=[r'scripts\run_daily_drive.py',r'scripts\verify_posts.py'])
    script=parser.parse_args().script
    root = Path(__file__).resolve().parents[1]
    wrapper = root.parent / 'run-task.ps1'
    if not wrapper.is_file():
        raise SystemExit('production runtime wrapper missing')
    log = root / 'logs' / 'scheduled-posting.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8') as stream:
        result = subprocess.run([
            'powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
            '-ExecutionPolicy', 'Bypass', '-File', str(wrapper),
            '-Script', script,
        ], cwd=root, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
