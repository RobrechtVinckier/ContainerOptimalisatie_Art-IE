"""Night staging moves to improve next-day loading throughput."""

from __future__ import annotations

import random
from typing import List, Tuple

from ..core.constants import (
    CONTAINER_METERS,
    YARD_HEIGHT,
    YARD_LENGTH,
    YARD_WIDTH,
)
from .stack_service import clone_stacks
from .timing_service import crane_move_seconds, weighted_xy_cost


def night_stage_for_day(
    stacks: List[List[List[dict]]],
    night_budget_s: float,
    day_seed: int,
    *,
    start_time_s: float = 0.0,
    crane_start: Tuple[float, float] = (2.0, 0.0),
) -> Tuple[List[dict], List[List[List[dict]]], float]:
    """Heuristically stage containers closer to truck-facing columns."""
    rng = random.Random(day_seed ^ 0x13579BDF)
    working = clone_stacks(stacks)
    moves: List[dict] = []
    crane_x = float(crane_start[0])
    crane_z = float(crane_start[1])
    time_used = float(start_time_s)

    def top_run_length(stack: List[dict], color_name: str) -> int:
        run = 0
        for existing in reversed(stack):
            if existing["color"] != color_name:
                break
            run += 1
        return run

    def find_open_z(dst_x: int, center_z: int) -> int | None:
        for radius in range(YARD_LENGTH):
            candidates = [center_z] if radius == 0 else [center_z - radius, center_z + radius]
            for z in candidates:
                if 0 <= z < YARD_LENGTH and len(working[dst_x][z]) < YARD_HEIGHT:
                    return z
        return None

    max_iters = 40
    for _ in range(max_iters):
        sources: List[Tuple[int, int, int, dict]] = []
        for src_x in range(YARD_WIDTH):
            for src_z in range(YARD_LENGTH):
                stack = working[src_x][src_z]
                if not stack:
                    continue
                # Stage containers toward truck-side width only.
                if src_x >= YARD_WIDTH - 1:
                    continue
                sources.append((src_x, src_z, len(stack) - 1, stack[-1]))

        if not sources:
            break

        best_candidate = None
        best_score = None

        for src_x, src_z, src_y, container in sources:
            for dst_x in (YARD_WIDTH - 1, YARD_WIDTH - 2):
                if dst_x <= src_x:
                    continue
                dst_z = find_open_z(dst_x, src_z)
                if dst_z is None:
                    continue

                dst_y = len(working[dst_x][dst_z])
                dst_stack = working[dst_x][dst_z]
                duration_seconds = crane_move_seconds(
                    crane_x=crane_x,
                    crane_z=crane_z,
                    src_x=src_x,
                    src_z=src_z,
                    src_level=src_y,
                    dst_x=dst_x,
                    dst_z=dst_z,
                    dst_level=dst_y,
                )
                if time_used + duration_seconds > night_budget_s:
                    continue

                weighted_cost = weighted_xy_cost(src_x, src_z, dst_x, dst_z)
                width_gain = float(dst_x - src_x) * CONTAINER_METERS["width"]
                top_support = float(top_run_length(dst_stack, container["color"]))
                same_color_stack_bonus = top_support * 0.45
                if not dst_stack:
                    same_color_stack_bonus += 0.25
                elif dst_stack[-1]["color"] != container["color"]:
                    same_color_stack_bonus -= 0.65
                local_alignment_bonus = max(0, 2 - abs(dst_z - src_z)) * CONTAINER_METERS["length"] * 0.18
                length_penalty = abs(dst_z - src_z) * CONTAINER_METERS["length"] * 0.16
                stack_penalty = dst_y * 0.12
                weighted_cost_penalty = weighted_cost * 0.1
                jitter = rng.random() * 0.0005
                move_score = (
                    width_gain * 1.0
                    + same_color_stack_bonus
                    + local_alignment_bonus
                    - length_penalty
                    - stack_penalty
                    - weighted_cost_penalty
                    + jitter
                ) / max(duration_seconds, 0.01)

                if best_score is None or move_score > best_score:
                    best_score = move_score
                    best_candidate = (
                        container,
                        src_x,
                        src_z,
                        src_y,
                        dst_x,
                        dst_z,
                        dst_y,
                        duration_seconds,
                    )

        if best_candidate is None or (best_score is not None and best_score <= 0.0):
            break

        (
            container,
            src_x,
            src_z,
            src_y,
            dst_x,
            dst_z,
            dst_y,
            duration_seconds,
        ) = best_candidate

        src_stack = working[src_x][src_z]
        dst_stack = working[dst_x][dst_z]
        moved = src_stack.pop()
        dst_stack.append(moved)

        t_start = time_used
        t_end = t_start + duration_seconds
        time_used = t_end
        crane_x = float(dst_x)
        crane_z = float(dst_z)

        moves.append(
            {
                "id": container["id"],
                "color": container["color"],
                "from": {"x": src_x, "z": src_z, "y": src_y},
                "to": {"x": dst_x, "z": dst_z, "y": dst_y},
                "weightedCost": weighted_xy_cost(src_x, src_z, dst_x, dst_z),
                "tStart": t_start,
                "tEnd": t_end,
                "durationSeconds": duration_seconds,
            }
        )

    return moves, working, time_used
