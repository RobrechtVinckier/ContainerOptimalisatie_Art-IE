from __future__ import annotations

import random
import time
from typing import Dict, List, Tuple

from algorithm.optimizer import OptimizerConfig, greedy_plan, tabu_improve
from algorithm.state import State

from . import schemas

YARD_WIDTH = 5
YARD_LENGTH = 10
YARD_HEIGHT = 4
TRUCK_LANE_WIDTH = 1
DEFAULT_CONTAINER_COUNT = 130
LENGTH_COST_WEIGHT = 10

CONTAINER_METERS = {
    "length": 12.19,
    "width": 2.44,
    "height": 2.59,
}

COLOR_ORDER = ("red", "green", "blue")
COLOR_TO_GROUP = {"red": 0, "green": 1, "blue": 2}
TARGET_PATTERNS = (
    ("red", "green", "blue", "red", "green"),
    ("green", "blue", "red", "green", "blue"),
    ("blue", "red", "green", "blue", "red"),
)

ALGORITHM_SETTINGS = schemas.AlgorithmSettings()


def yard_config_payload() -> dict:
    return {
        "width": YARD_WIDTH,
        "length": YARD_LENGTH,
        "height": YARD_HEIGHT,
        "truckLaneWidth": TRUCK_LANE_WIDTH,
        "containerCount": DEFAULT_CONTAINER_COUNT,
        "lengthCostWeight": LENGTH_COST_WEIGHT,
        "containerMeters": CONTAINER_METERS,
    }


def get_algorithm_settings() -> schemas.AlgorithmSettings:
    return ALGORITHM_SETTINGS


def update_algorithm_settings(patch: schemas.AlgorithmSettingsPatch) -> schemas.AlgorithmSettings:
    global ALGORITHM_SETTINGS

    current = ALGORITHM_SETTINGS.model_dump()
    updates = patch.model_dump(exclude_none=True)
    current.update(updates)
    ALGORITHM_SETTINGS = schemas.AlgorithmSettings(**current)
    return ALGORITHM_SETTINGS


def create_empty_stacks() -> List[List[List[dict]]]:
    return [[[] for _ in range(YARD_LENGTH)] for _ in range(YARD_WIDTH)]


def clone_stacks(stacks: List[List[List[dict]]]) -> List[List[List[dict]]]:
    return [[[{"id": c["id"], "color": c["color"]} for c in stack] for stack in columns] for columns in stacks]


def target_color_for_slot(x: int, z: int) -> str:
    return TARGET_PATTERNS[z % len(TARGET_PATTERNS)][x]


def summarize_stacks(stacks: List[List[List[dict]]]) -> dict:
    color_count = {"red": 0, "green": 0, "blue": 0}
    in_target_slot = 0
    total = 0

    for x in range(YARD_WIDTH):
        for z in range(YARD_LENGTH):
            target = target_color_for_slot(x, z)
            for container in stacks[x][z]:
                color_count[container["color"]] += 1
                if container["color"] == target:
                    in_target_slot += 1
                total += 1

    score = 1.0 if total == 0 else in_target_slot / total
    return {
        "colorCount": color_count,
        "total": total,
        "inTargetSlot": in_target_slot,
        "placementScore": score,
    }


def is_solved(stacks: List[List[List[dict]]]) -> bool:
    for x in range(YARD_WIDTH):
        for z in range(YARD_LENGTH):
            target = target_color_for_slot(x, z)
            for container in stacks[x][z]:
                if container["color"] != target:
                    return False
    return True


def random_configuration(seed: int | None = None, container_count: int = DEFAULT_CONTAINER_COUNT) -> dict:
    resolved_seed = int(seed if seed is not None else time.time_ns() % 1_000_000_000)
    rng = random.Random(resolved_seed)

    max_capacity = YARD_WIDTH * YARD_LENGTH * YARD_HEIGHT
    if container_count > max_capacity:
        raise ValueError(f"containerCount={container_count} exceeds capacity={max_capacity}")

    stacks = create_empty_stacks()
    heights = [[0 for _ in range(YARD_LENGTH)] for _ in range(YARD_WIDTH)]

    remaining = container_count
    while remaining > 0:
        x = rng.randrange(YARD_WIDTH)
        z = rng.randrange(YARD_LENGTH)
        if heights[x][z] >= YARD_HEIGHT:
            continue
        heights[x][z] += 1
        remaining -= 1

    next_id = 1
    for x in range(YARD_WIDTH):
        for z in range(YARD_LENGTH):
            for _ in range(heights[x][z]):
                color = COLOR_ORDER[rng.randrange(len(COLOR_ORDER))]
                stacks[x][z].append({"id": f"C{next_id:04d}", "color": color})
                next_id += 1

    return {
        "seed": resolved_seed,
        "stacks": stacks,
        "summary": summarize_stacks(stacks),
    }


def _state_from_stacks(stacks: List[List[List[dict]]]) -> Tuple[State, Dict[int, dict]]:
    # Algorithm axis mapping:
    # algorithm X -> yard length (z), algorithm Y -> yard width (x)
    yard = [[[] for _ in range(YARD_WIDTH)] for _ in range(YARD_LENGTH)]
    group: List[int] = []
    metadata: Dict[int, dict] = {}

    for x in range(YARD_WIDTH):
        for z in range(YARD_LENGTH):
            for container in stacks[x][z]:
                cid = len(group)
                group_id = COLOR_TO_GROUP[container["color"]]
                group.append(group_id)
                yard[z][x].append(cid)
                metadata[cid] = {"id": container["id"], "color": container["color"]}

    state = State.build_from_yard(X=YARD_LENGTH, Y=YARD_WIDTH, H=YARD_HEIGHT, yard=yard, group=group)
    state.crane_pos = (0, 0)
    state.time_used = 0.0
    return state, metadata


def _optimizer_config(settings: schemas.AlgorithmSettings) -> OptimizerConfig:
    return OptimizerConfig(
        seed=settings.seed,
        lam=settings.lam,
        night_budget_s=settings.nightBudget,
        energy_weight=settings.energyWeight,
        energy_x_cost=settings.energyXCost,
        energy_y_cost=settings.energyYCost,
        energy_z_cost=settings.energyZCost,
        top_groups=settings.topGroups,
        src_limit=settings.srcLimit,
        dst_limit_per_src=settings.dstLimit,
        x_radius=settings.xRadius,
        y_radius=settings.yRadius,
        y_aware=settings.yAware,
        tabu_iters=settings.tabuIters,
        tabu_len=settings.tabuLen,
        tabu_mode=settings.tabuMode,
        selection_mode=settings.selectionMode,
        top_k=settings.topK,
        non_improving_penalty=settings.nonImprovingPenalty,
        plateau_iters=settings.plateauIters,
        shake_enabled=settings.shakeEnabled,
    )


def _convert_moves_to_frontend(
    moves,
    stacks: List[List[List[dict]]],
) -> Tuple[List[dict], List[List[List[dict]]]]:
    working = clone_stacks(stacks)
    output: List[dict] = []

    for move in moves:
        src_x = move.src[1]
        src_z = move.src[0]
        dst_x = move.dst[1]
        dst_z = move.dst[0]

        source = working[src_x][src_z]
        destination = working[dst_x][dst_z]
        if not source or len(destination) >= YARD_HEIGHT:
            continue

        container = source.pop()
        from_y = len(source)
        to_y = len(destination)
        destination.append(container)

        weighted_cost = abs(src_x - dst_x) + LENGTH_COST_WEIGHT * abs(src_z - dst_z)
        output.append(
            {
                "id": container["id"],
                "color": container["color"],
                "from": {"x": src_x, "z": src_z, "y": from_y},
                "to": {"x": dst_x, "z": dst_z, "y": to_y},
                "weightedCost": weighted_cost,
            }
        )

    return output, working


def solve_stacks(stacks: List[List[List[dict]]], settings_patch: schemas.AlgorithmSettingsPatch | None = None) -> dict:
    if len(stacks) != YARD_WIDTH or any(len(column) != YARD_LENGTH for column in stacks):
        raise ValueError("Invalid stack dimensions")

    settings = get_algorithm_settings()
    if settings_patch is not None:
        merged = settings.model_dump()
        merged.update(settings_patch.model_dump(exclude_none=True))
        settings = schemas.AlgorithmSettings(**merged)

    initial = clone_stacks(stacks)
    state, _metadata = _state_from_stacks(initial)
    cfg = _optimizer_config(settings)

    greedy_state = state.clone()
    greedy_moves = greedy_plan(greedy_state, cfg)

    tabu_state = greedy_state.clone()
    tabu_moves, _best_state = tabu_improve(tabu_state, cfg)

    full_moves = list(greedy_moves) + list(tabu_moves)
    frontend_moves, final_stacks = _convert_moves_to_frontend(full_moves, initial)
    total_weighted_cost = sum(move["weightedCost"] for move in frontend_moves)

    return {
        "moves": frontend_moves,
        "solved": is_solved(final_stacks),
        "totalWeightedCost": total_weighted_cost,
        "finalSummary": summarize_stacks(final_stacks),
        "finalStacks": final_stacks,
    }
