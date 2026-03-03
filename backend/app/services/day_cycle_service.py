"""Services for building daytime truck loading schedules."""

from __future__ import annotations

import hashlib
import random
from typing import Dict, List, Tuple

from ..core.constants import (
    COMPANY_BY_COLOR,
    DAY_COMPANY_SWITCH_PENALTY,
    DAY_DURATION_SECONDS,
    DAY_END_SECONDS,
    DAY_INCOMPLETE_COMPANY_SWITCH_PENALTY,
    DAY_START_SECONDS,
    DAY_TRUCK_SLOTS,
    DAY_ENERGY_WEIGHT,
    LENGTH_COST_WEIGHT,
    TRUCK_FLOW_HEADWAY_SECONDS,
    TRUCK_LOAD_BUFFER_SECONDS,
    TRUCK_PICKUP_X,
    YARD_HEIGHT,
    YARD_LENGTH,
    YARD_WIDTH,
)
from .stack_service import clone_stacks
from .timing_service import crane_move_seconds, weighted_xy_cost


def _is_hex_color(color_value: str) -> bool:
    if len(color_value) != 7 or not color_value.startswith("#"):
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in color_value[1:])


def _company_profile_for_color(color_name: str) -> Dict[str, str]:
    known = COMPANY_BY_COLOR.get(color_name)
    if known is not None:
        return {"company": known["company"], "truckColor": known["truckColor"]}

    digest = hashlib.sha1(color_name.encode("utf-8")).hexdigest()
    generated_color = color_name if _is_hex_color(color_name) else f"#{digest[:6]}"
    return {
        "company": f"Group {digest[:4].upper()} Logistics",
        "truckColor": generated_color,
    }


def slot_to_stack_z(slot_index: int) -> int:
    """Map truck slot index to nearest yard z-index."""
    slot_span = YARD_LENGTH / DAY_TRUCK_SLOTS
    z = int(round((slot_index + 0.5) * slot_span - 0.5))
    return max(0, min(YARD_LENGTH - 1, z))


def top_containers(stacks: List[List[List[dict]]]) -> List[Tuple[int, int, int, dict]]:
    """Return all currently accessible top containers."""
    out: List[Tuple[int, int, int, dict]] = []
    for x in range(YARD_WIDTH):
        for z in range(YARD_LENGTH):
            stack = stacks[x][z]
            if not stack:
                continue
            y = len(stack) - 1
            out.append((x, z, y, stack[y]))
    return out


def estimate_truck_timing(
    *,
    load_start: float,
    load_end: float,
    slot_index: int,
    lane_flow_free_at: float,
) -> Tuple[float, float, float]:
    """Estimate arrival/departure with lane headway constraints."""
    approach_time = 38.0 + slot_index * 2.0
    arrival_target = max(0.0, load_start - approach_time)
    arrival_time = max(arrival_target, lane_flow_free_at)
    lane_cursor = arrival_time + TRUCK_FLOW_HEADWAY_SECONDS

    depart_ready = load_end + TRUCK_LOAD_BUFFER_SECONDS
    depart_time = max(depart_ready, lane_cursor)
    lane_wait_seconds = depart_time - depart_ready
    return arrival_time, depart_time, lane_wait_seconds


def build_day_cycle_plan(stacks: List[List[List[dict]]], day_seed: int) -> dict:
    """Build deterministic day schedule optimizing crane and lane efficiency."""
    rng = random.Random(day_seed ^ 0xBADC0DE)
    working = clone_stacks(stacks)
    remaining_by_color: Dict[str, int] = {}
    for x in range(YARD_WIDTH):
        for z in range(YARD_LENGTH):
            for container in working[x][z]:
                color_name = container["color"]
                remaining_by_color[color_name] = remaining_by_color.get(color_name, 0) + 1
    company_profiles = {color_name: _company_profile_for_color(color_name) for color_name in remaining_by_color}
    slot_z_map = [slot_to_stack_z(slot) for slot in range(DAY_TRUCK_SLOTS)]
    slot_free_at = [0.0] * DAY_TRUCK_SLOTS
    lane_flow_free_at = 0.0
    company_trips: Dict[str, int] = {
        profile["company"]: 0 for profile in company_profiles.values()
    }

    crane_time = 0.0
    crane_x = 2.0
    crane_z = 0.0
    truck_seq = 0
    total_crane_weighted_cost = 0.0
    total_lane_wait_seconds = 0.0
    jobs: List[dict] = []

    while True:
        candidates = top_containers(working)
        if not candidates:
            break

        best_choice = None
        best_score = None
        for source_x, source_z, source_y, container in candidates:
            for slot_index in range(DAY_TRUCK_SLOTS):
                slot_z = slot_z_map[slot_index]
                horizontal_weighted_cost = weighted_xy_cost(crane_x, crane_z, source_x, source_z) + weighted_xy_cost(
                    source_x,
                    source_z,
                    TRUCK_PICKUP_X,
                    slot_z,
                )
                crane_task_seconds = crane_move_seconds(
                    crane_x=crane_x,
                    crane_z=crane_z,
                    src_x=source_x,
                    src_z=source_z,
                    src_level=source_y,
                    dst_x=TRUCK_PICKUP_X,
                    dst_z=slot_z,
                    dst_level=0,
                )
                tentative_load_start = max(crane_time, slot_free_at[slot_index])
                tentative_load_end = tentative_load_start + crane_task_seconds
                arrival_time, depart_time, lane_wait_seconds = estimate_truck_timing(
                    load_start=tentative_load_start,
                    load_end=tentative_load_end,
                    slot_index=slot_index,
                    lane_flow_free_at=lane_flow_free_at,
                )
                if depart_time > DAY_DURATION_SECONDS:
                    continue
                same_company_bonus = -0.35 if jobs and jobs[-1]["containerColor"] == container["color"] else 0.0
                company_switch_penalty = 0.0
                if jobs and jobs[-1]["containerColor"] != container["color"]:
                    previous_color = jobs[-1]["containerColor"]
                    company_switch_penalty += DAY_COMPANY_SWITCH_PENALTY
                    if remaining_by_color.get(previous_color, 0) > 0:
                        company_switch_penalty += DAY_INCOMPLETE_COMPANY_SWITCH_PENALTY
                # Optimize for crane efficiency first: expensive lengthwise crane movement
                # is encoded in horizontal_weighted_cost (length axis weighted 10x).
                score = (
                    depart_time
                    + lane_wait_seconds * 2.0
                    + horizontal_weighted_cost * DAY_ENERGY_WEIGHT
                    + company_switch_penalty
                    + same_company_bonus
                    + rng.random() * 0.001
                )
                if best_score is None or score < best_score:
                    best_score = score
                    best_choice = (
                        source_x,
                        source_z,
                        source_y,
                        container,
                        slot_index,
                        slot_z,
                        horizontal_weighted_cost,
                        crane_task_seconds,
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
            horizontal_weighted_cost,
            crane_task_seconds,
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

        color_name = container["color"]
        profile = company_profiles.setdefault(color_name, _company_profile_for_color(color_name))
        company = profile["company"]
        company_color = profile["truckColor"]
        if company not in company_trips:
            company_trips[company] = 0
        company_trips[company] += 1
        remaining_by_color[color_name] = remaining_by_color.get(color_name, 0) - 1

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
            "craneWeightedCost": horizontal_weighted_cost,
            "laneWaitSeconds": lane_wait,
            "craneTaskSeconds": crane_task_seconds,
        }
        jobs.append(job)

        crane_time = load_end
        crane_x = float(TRUCK_PICKUP_X)
        crane_z = float(slot_z)
        total_crane_weighted_cost += horizontal_weighted_cost
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
