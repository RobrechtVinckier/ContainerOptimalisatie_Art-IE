"""Smoke-test the main backend/API/CLI flows.

This script is intentionally lightweight and deterministic so it can be
run after each refactor patch.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app import database, main, schemas


def run_backend_function_smoke() -> None:
    payload = database.random_configuration(seed=404, container_count=20)
    assert payload["seed"] == 404
    assert payload["summary"]["total"] == 20
    assert len(payload["stacks"]) == database.YARD_WIDTH
    assert len(payload["stacks"][0]) == database.YARD_LENGTH

    solve = database.solve_stacks(
        payload["stacks"],
        settings_patch=schemas.AlgorithmSettingsPatch(seed=404, tabuIters=80),
    )
    assert "moves" in solve
    assert "dayCycle" in solve
    assert "nightStats" in solve
    assert len(solve["finalStacks"]) == database.YARD_WIDTH
    assert len(solve["finalStacks"][0]) == database.YARD_LENGTH


def run_api_smoke() -> None:
    async def _call_endpoints() -> dict:
        health = await main.health()
        assert health["status"] == "ok"

        random_payload = await main.create_random_simulation(
            schemas.RandomSimulationRequest(seed=505, containerCount=22)
        )
        solve_payload = await main.solve_simulation(
            schemas.SolveSimulationRequest(
                stacks=random_payload["stacks"],
                settings=schemas.AlgorithmSettingsPatch(seed=505, tabuIters=80),
            )
        )
        return solve_payload

    body = asyncio.run(_call_endpoints())
    assert "moves" in body
    assert "finalSummary" in body
    assert "dayCycle" in body
    assert "nightStats" in body


def run_cli_smoke() -> None:
    command = [
        sys.executable,
        "algorithm/main.py",
        "--seed",
        "9",
        "--X",
        "4",
        "--Y",
        "3",
        "--H",
        "3",
        "--groups",
        "3",
        "--per-group",
        "3",
        "--tabu-iters",
        "30",
    ]
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"CLI smoke failed: {completed.stderr}")
    if "Tabu result (best found during search)" not in completed.stdout:
        raise RuntimeError("CLI smoke output missing expected summary marker")


def main_smoke() -> None:
    run_backend_function_smoke()
    run_api_smoke()
    run_cli_smoke()
    print("Smoke test passed.")


if __name__ == "__main__":
    main_smoke()
