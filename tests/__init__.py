"""Test package bootstrap helpers."""

from __future__ import annotations

import sys
from pathlib import Path

# Keep legacy tests working without requiring PYTHONPATH=algorithm.
REPO_ROOT = Path(__file__).resolve().parent.parent
ALGORITHM_DIR = REPO_ROOT / "algorithm"
if str(ALGORITHM_DIR) not in sys.path:
    sys.path.insert(0, str(ALGORITHM_DIR))
