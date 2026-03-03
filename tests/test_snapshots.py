from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

from backend.app import database

SNAPSHOT_PATH = Path(__file__).resolve().parent / "snapshots" / "baseline_signatures.json"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _round_float(value: float, ndigits: int = 6) -> float:
    return round(float(value), ndigits)


def _stack_heights(stacks: List[List[List[dict]]]) -> List[List[int]]:
    return [[len(stacks[x][z]) for z in range(database.YARD_LENGTH)] for x in range(database.YARD_WIDTH)]


def _load_snapshot() -> Dict[str, Any]:
    with SNAPSHOT_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _random_signature(seed: int, container_count: int) -> Dict[str, Any]:
    payload = database.random_configuration(seed=seed, container_count=container_count)
    flat = [container for column in payload["stacks"] for stack in column for container in stack]
    return {
        "seed": payload["seed"],
        "summary": payload["summary"],
        "heights": _stack_heights(payload["stacks"]),
        "first5": flat[:5],
        "last5": flat[-5:],
    }


def _solve_signature(seed: int, container_count: int) -> Dict[str, Any]:
    random_payload = database.random_configuration(seed=seed, container_count=container_count)
    payload = database.solve_stacks(random_payload["stacks"])
    moves = payload["moves"]
    move_tail = moves[:5] + moves[-5:] if len(moves) >= 10 else moves
    first_last_moves = [
        {
            "id": move["id"],
            "from": move["from"],
            "to": move["to"],
            "weightedCost": move["weightedCost"],
            "tStart": _round_float(move["tStart"]),
            "tEnd": _round_float(move["tEnd"]),
            "durationSeconds": _round_float(move["durationSeconds"]),
        }
        for move in move_tail
    ]
    night_stats = dict(payload["nightStats"])
    night_stats["timeUsedSeconds"] = _round_float(night_stats["timeUsedSeconds"])
    night_stats["budgetSeconds"] = _round_float(night_stats["budgetSeconds"])
    night_stats["startPlacementScore"] = _round_float(night_stats["startPlacementScore"])
    night_stats["endPlacementScore"] = _round_float(night_stats["endPlacementScore"])

    day_stats = dict(payload["dayCycle"]["stats"])
    day_stats["totalCraneWeightedCost"] = _round_float(day_stats["totalCraneWeightedCost"])
    day_stats["totalLaneWaitSeconds"] = _round_float(day_stats["totalLaneWaitSeconds"])
    day_stats["makespanSeconds"] = _round_float(day_stats["makespanSeconds"])
    day_stats["score"] = _round_float(day_stats["score"])

    return {
        "moves_len": len(moves),
        "solved": payload["solved"],
        "totalWeightedCost": payload["totalWeightedCost"],
        "finalSummary": payload["finalSummary"],
        "nightStats": night_stats,
        "dayStats": day_stats,
        "first_last_moves": first_last_moves,
        "final_heights": _stack_heights(payload["finalStacks"]),
    }


def _extract_match(pattern: str, line: str, description: str) -> re.Match[str]:
    match = re.match(pattern, line)
    if match is None:
        raise AssertionError(f"Could not parse {description}: {line!r}")
    return match


def _cli_signature() -> Dict[str, Any]:
    command = [
        sys.executable,
        "algorithm/main.py",
        "--seed",
        "1",
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
        "50",
    ]
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise AssertionError(f"CLI run failed with code {completed.returncode}: {completed.stderr}")

    lines = completed.stdout.splitlines()
    initial_line = next(line for line in lines if line.startswith("Initial cluster cost:"))
    greedy_moves_line = next(line for line in lines if line.startswith("  moves:"))
    greedy_time_line = next(line for line in lines if line.startswith("  time_used:"))
    greedy_cluster_line = next(line for line in lines if line.startswith("  cluster_cost:"))
    tabu_moves_line = next(line for line in lines if line.startswith("  moves_applied_in_search:"))
    tabu_time_line = next(line for line in lines if line.startswith("  best_time_used:"))
    tabu_cluster_line = next(line for line in lines if line.startswith("  best_cluster_cost:"))
    move_lines = [line for line in lines if line.startswith("  t=")]
    truncated_line = next((line for line in lines if line.startswith("  ... (")), None)

    initial_match = _extract_match(r"^Initial cluster cost: ([0-9]+\.[0-9]+)$", initial_line, "initial cluster line")
    greedy_moves_match = _extract_match(r"^  moves: ([0-9]+)$", greedy_moves_line, "greedy moves line")
    greedy_time_match = _extract_match(
        r"^  time_used: ([0-9]+\.[0-9]+)s / ([0-9]+\.[0-9]+)s$",
        greedy_time_line,
        "greedy time line",
    )
    greedy_cluster_match = _extract_match(
        r"^  cluster_cost: ([0-9]+\.[0-9]+) -> ([0-9]+\.[0-9]+)  \(delta [+-][0-9]+\.[0-9]+\)$",
        greedy_cluster_line,
        "greedy cluster line",
    )
    tabu_moves_match = _extract_match(r"^  moves_applied_in_search: ([0-9]+)$", tabu_moves_line, "tabu moves line")
    tabu_time_match = _extract_match(
        r"^  best_time_used: ([0-9]+\.[0-9]+)s / ([0-9]+\.[0-9]+)s$",
        tabu_time_line,
        "tabu time line",
    )
    tabu_cluster_match = _extract_match(
        r"^  best_cluster_cost: ([0-9]+\.[0-9]+) -> ([0-9]+\.[0-9]+)  \(delta [+-][0-9]+\.[0-9]+\)$",
        tabu_cluster_line,
        "tabu cluster line",
    )
    truncated_count = 0
    if truncated_line is not None:
        truncated_match = _extract_match(r"^  \.\.\. \(([0-9]+) more\)$", truncated_line, "truncated move line")
        truncated_count = int(truncated_match.group(1))

    return {
        "initialClusterCost": float(initial_match.group(1)),
        "greedyMoves": int(greedy_moves_match.group(1)),
        "greedyTimeUsedSeconds": float(greedy_time_match.group(1)),
        "greedyBudgetSeconds": float(greedy_time_match.group(2)),
        "greedyClusterStart": float(greedy_cluster_match.group(1)),
        "greedyClusterEnd": float(greedy_cluster_match.group(2)),
        "tabuMovesApplied": int(tabu_moves_match.group(1)),
        "tabuBestTimeUsedSeconds": float(tabu_time_match.group(1)),
        "tabuBudgetSeconds": float(tabu_time_match.group(2)),
        "tabuClusterStart": float(tabu_cluster_match.group(1)),
        "tabuClusterEnd": float(tabu_cluster_match.group(2)),
        "firstMoveLines": move_lines[:3],
        "truncatedMoveCount": truncated_count,
    }


class TestSnapshots(unittest.TestCase):
    def test_random_configuration_snapshot(self) -> None:
        snapshots = _load_snapshot()
        signature = _random_signature(seed=2025, container_count=18)
        self.assertEqual(signature, snapshots["random_configuration_seed_2025_count_18"])

    def test_solve_snapshot(self) -> None:
        snapshots = _load_snapshot()
        signature = _solve_signature(seed=2025, container_count=18)
        self.assertEqual(signature, snapshots["solve_stacks_seed_2025_count_18"])

    def test_cli_snapshot_signature(self) -> None:
        snapshots = _load_snapshot()
        signature = _cli_signature()
        self.assertEqual(signature, snapshots["algorithm_cli_signature_seed_1"])


if __name__ == "__main__":
    unittest.main()
