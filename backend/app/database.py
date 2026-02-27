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
TRUCK_LANE_WIDTH = 2
DEFAULT_CONTAINER_COUNT = 130
LENGTH_COST_WEIGHT = 10
DAY_TRUCK_SLOTS = 9
TRUCK_PICKUP_X = YARD_WIDTH
TRUCK_FLOW_HEADWAY_SECONDS = 6.0
TRUCK_LOAD_BUFFER_SECONDS = 20.0
DAY_START_SECONDS = 6 * 3600
DAY_END_SECONDS = 22 * 3600
DAY_DURATION_SECONDS = DAY_END_SECONDS - DAY_START_SECONDS

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
COMPANY_BY_COLOR = {
    "red": {"company": "Aster Freight", "truckColor": "#cc4347"},
    "green": {"company": "Boreal Cargo", "truckColor": "#2d9c60"},
    "blue": {"company": "Cobalt Haul", "truckColor": "#3e64c7"},
}

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


def _normalize_container(container) -> dict:
    if isinstance(container, dict):
        cid = container.get("id")
        color = container.get("color")
    else:
        cid = getattr(container, "id", None)
        color = getattr(container, "color", None)

    if cid is None or color is None:
        raise ValueError("Container payload must include id and color")

    return {"id": str(cid), "color": str(color)}


def clone_stacks(stacks) -> List[List[List[dict]]]:
    return [[[_normalize_container(container) for container in stack] for stack in columns] for columns in stacks]


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
        t_start = float(getattr(move, "t_start", 0.0))
        t_end = float(getattr(move, "t_end", t_start))
        output.append(
            {
                "id": container["id"],
                "color": container["color"],
                "from": {"x": src_x, "z": src_z, "y": from_y},
                "to": {"x": dst_x, "z": dst_z, "y": to_y},
                "weightedCost": weighted_cost,
                "tStart": t_start,
                "tEnd": t_end,
                "durationSeconds": max(0.0, t_end - t_start),
            }
        )

    return output, working


def _slot_to_stack_z(slot_index: int) -> int:
    slot_span = YARD_LENGTH / DAY_TRUCK_SLOTS
    z = int(round((slot_index + 0.5) * slot_span - 0.5))
    return max(0, min(YARD_LENGTH - 1, z))


def _top_containers(stacks: List[List[List[dict]]]) -> List[Tuple[int, int, int, dict]]:
    out: List[Tuple[int, int, int, dict]] = []
    for x in range(YARD_WIDTH):
        for z in range(YARD_LENGTH):
            stack = stacks[x][z]
            if not stack:
                continue
            y = len(stack) - 1
            out.append((x, z, y, stack[y]))
    return out


def _weighted_xy_cost(src_x: int | float, src_z: int | float, dst_x: int | float, dst_z: int | float) -> float:
    return float(abs(src_x - dst_x) + LENGTH_COST_WEIGHT * abs(src_z - dst_z))


def _estimate_truck_timing(
    *,
    load_start: float,
    load_end: float,
    slot_index: int,
    lane_flow_free_at: float,
) -> Tuple[float, float, float]:
    approach_time = 38.0 + slot_index * 2.0
    arrival_target = max(0.0, load_start - approach_time)
    arrival_time = max(arrival_target, lane_flow_free_at)
    lane_cursor = arrival_time + TRUCK_FLOW_HEADWAY_SECONDS

    depart_ready = load_end + TRUCK_LOAD_BUFFER_SECONDS
    depart_time = max(depart_ready, lane_cursor)
    lane_wait_seconds = depart_time - depart_ready
    return arrival_time, depart_time, lane_wait_seconds


def _build_day_cycle_plan(stacks: List[List[List[dict]]], day_seed: int) -> dict:
    rng = random.Random(day_seed ^ 0xBADC0DE)
    working = clone_stacks(stacks)
    slot_z_map = [_slot_to_stack_z(slot) for slot in range(DAY_TRUCK_SLOTS)]
    slot_free_at = [0.0] * DAY_TRUCK_SLOTS
    lane_flow_free_at = 0.0
    company_trips: Dict[str, int] = {
        COMPANY_BY_COLOR["red"]["company"]: 0,
        COMPANY_BY_COLOR["green"]["company"]: 0,
        COMPANY_BY_COLOR["blue"]["company"]: 0,
    }

    crane_time = 0.0
    crane_x = 2.0
    crane_z = 0.0
    truck_seq = 0
    total_crane_weighted_cost = 0.0
    total_lane_wait_seconds = 0.0
    jobs: List[dict] = []

    while True:
        candidates = _top_containers(working)
        if not candidates:
            break

        best_choice = None
        best_score = None
        for source_x, source_z, source_y, container in candidates:
            for slot_index in range(DAY_TRUCK_SLOTS):
                slot_z = slot_z_map[slot_index]
                to_source_cost = _weighted_xy_cost(crane_x, crane_z, source_x, source_z)
                source_to_truck_cost = _weighted_xy_cost(source_x, source_z, TRUCK_PICKUP_X, slot_z)
                tentative_load_start = max(crane_time + to_source_cost, slot_free_at[slot_index])
                tentative_load_end = tentative_load_start + source_to_truck_cost
                arrival_time, depart_time, lane_wait_seconds = _estimate_truck_timing(
                    load_start=tentative_load_start,
                    load_end=tentative_load_end,
                    slot_index=slot_index,
                    lane_flow_free_at=lane_flow_free_at,
                )
                if depart_time > DAY_DURATION_SECONDS:
                    continue
                # bias lightly to keep same company batches together for realistic dispatching
                same_company_bonus = -0.35 if jobs and jobs[-1]["containerColor"] == container["color"] else 0.0
                score = depart_time + lane_wait_seconds * 2.0 + same_company_bonus + rng.random() * 0.001
                if best_score is None or score < best_score:
                    best_score = score
                    best_choice = (
                        source_x,
                        source_z,
                        source_y,
                        container,
                        slot_index,
                        slot_z,
                        to_source_cost,
                        source_to_truck_cost,
                        tentative_load_start,
                        tentative_load_end,
                        arrival_time,
                        depart_time,
                        lane_wait_seconds,
                    )

        if best_choice is None:
            break

        (
            source_x,
            source_z,
            source_y,
            container,
            slot_index,
            slot_z,
            to_source_cost,
            source_to_truck_cost,
            load_start,
            load_end,
            arrival_time,
            depart_time,
            lane_wait,
        ) = best_choice

        stack = working[source_x][source_z]
        if not stack:
            continue
        top = stack.pop()
        if top["id"] != container["id"]:
            # Defensive correction in case of stale candidate tie during mutation.
            container = top
            source_y = len(stack)

        company = COMPANY_BY_COLOR[container["color"]]["company"]
        company_color = COMPANY_BY_COLOR[container["color"]]["truckColor"]
        company_trips[company] += 1

        lane_flow_free_at = arrival_time + TRUCK_FLOW_HEADWAY_SECONDS
        lane_flow_free_at = depart_time + TRUCK_FLOW_HEADWAY_SECONDS
        slot_free_at[slot_index] = depart_time + TRUCK_FLOW_HEADWAY_SECONDS

        truck_seq += 1
        job = {
            "jobIndex": len(jobs) + 1,
            "truckId": f"{company.split()[0][0]}-{truck_seq:03d}",
            "company": company,
            "companyColor": company_color,
            "containerId": container["id"],
            "containerColor": container["color"],
            "source": {"x": source_x, "z": source_z, "y": source_y},
            "slotIndex": slot_index,
            "slotZ": slot_z,
            "arrivalTime": arrival_time,
            "loadStartTime": load_start,
            "loadEndTime": load_end,
            "departTime": depart_time,
            "craneWeightedCost": to_source_cost + source_to_truck_cost,
            "laneWaitSeconds": lane_wait,
        }
        jobs.append(job)

        crane_time = load_end
        crane_x = float(TRUCK_PICKUP_X)
        crane_z = float(slot_z)
        total_crane_weighted_cost += to_source_cost + source_to_truck_cost
        total_lane_wait_seconds += lane_wait

    makespan_seconds = max((job["departTime"] for job in jobs), default=0.0)
    remaining_containers = sum(len(stack) for column in working for stack in column)
    score_denominator = total_crane_weighted_cost + total_lane_wait_seconds * 2.0 + makespan_seconds * 0.2 + 1.0
    score = 10000.0 / score_denominator

    return {
        "slots": DAY_TRUCK_SLOTS,
        "jobs": jobs,
        "stats": {
            "totalJobs": len(jobs),
            "trucksUsed": len({job["truckId"] for job in jobs}),
            "companyTrips": company_trips,
            "totalCraneWeightedCost": total_crane_weighted_cost,
            "totalLaneWaitSeconds": total_lane_wait_seconds,
            "makespanSeconds": makespan_seconds,
            "score": score,
            "lengthCostWeight": LENGTH_COST_WEIGHT,
            "dayStartSeconds": DAY_START_SECONDS,
            "dayEndSeconds": DAY_END_SECONDS,
            "dayDurationSeconds": DAY_DURATION_SECONDS,
            "remainingContainers": remaining_containers,
            "completedWithinWindow": remaining_containers == 0,
        },
    }


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
    initial_summary = summarize_stacks(initial)
    final_summary = summarize_stacks(final_stacks)

    night_stats = {
        "greedyMoveCount": len(greedy_moves),
        "tabuMoveCount": len(tabu_moves),
        "totalMoves": len(frontend_moves),
        "timeUsedSeconds": float(tabu_state.time_used),
        "budgetSeconds": float(settings.nightBudget),
        "startPlacementScore": initial_summary["placementScore"],
        "endPlacementScore": final_summary["placementScore"],
        "lengthCostWeight": LENGTH_COST_WEIGHT,
    }
    day_cycle = _build_day_cycle_plan(final_stacks, day_seed=settings.seed)

    return {
        "moves": frontend_moves,
        "solved": is_solved(final_stacks),
        "totalWeightedCost": total_weighted_cost,
        "finalSummary": final_summary,
        "finalStacks": final_stacks,
        "nightStats": night_stats,
        "dayCycle": day_cycle,
    }
