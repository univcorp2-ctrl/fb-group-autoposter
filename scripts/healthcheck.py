from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.orchestrator import healthcheck

if __name__ == "__main__":
    raise SystemExit(healthcheck(Settings.load()))
