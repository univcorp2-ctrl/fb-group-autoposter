from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.orchestrator import run_approval_poll

if __name__ == "__main__":
    settings = Settings.load()
    print(f"handled={run_approval_poll(settings)}")
