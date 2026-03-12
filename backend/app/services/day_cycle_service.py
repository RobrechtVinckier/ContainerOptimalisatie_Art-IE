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

PREFERRED_COMPANY_CHUNK = 4
MAX_COMPANY_CHUNK = 6
EARLY_SWITCH_PENALTY = 280.0
LONG_RUN_CONTINUATION_PENALTY = 150.0
ALTERNATE_WAVE_SWITCH_BONUS = 70.0


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


def _stack_top_run_length(stack: List[dict]) -> int:
    if not stack:
        return 0
    top_color = stack[-1]["color"]
    run = 0
    for container in reversed(stack):
        if container["color"] != top_color:
            break
        run += 1
    return run


def _useful_wave_run_length(stack: List[dict]) -> int:
    return min(_stack_top_run_length(stack), PREFERRED_COMPANY_CHUNK)


def _current_company_run(jobs: List[dict]) -> Tuple[str | None, int]:
    if not jobs:
        return None, 0
    last_color = jobs[-1]["containerColor"]
    run_length = 0
    for job in reversed(jobs):
        if job["containerColor"] != last_color:
            break
        run_length += 1
    return last_color, run_length


def _target_chunk_size(metrics_by_color: Dict[str, Dict[str, float]], color_name: str) -> int:
    metrics = metrics_by_color.get(color_name, {})
    top_count = metrics.get("topCount", 0.0)
    wave_potential = metrics.get("wavePotential", 0.0)
    extra = 1 if min(top_count, wave_potential) >= 6.0 else 0
    return max(3, min(MAX_COMPANY_CHUNK, PREFERRED_COMPANY_CHUNK + extra))


def _avg_access_cost(metrics_by_color: Dict[str, Dict[str, float]], color_name: str) -> float:
    metrics = metrics_by_color.get(color_name, {})
    top_count = max(1.0, metrics.get("topCount", 0.0))
    return metrics.get("widthCost", 0.0) / top_count


def _should_rotate_company_chunk(
    *,
    active_color: str | None,
    last_color: str | None,
    run_length: int,
    current_time_s: float,
    color_zone_by_name: Dict[str, int],
    accessible_metrics: Dict[str, Dict[str, float]],
) -> bool:
    if active_color is None or last_color is None or active_color != last_color:
        return False
    if len(accessible_metrics) <= 1:
        return False

    target_chunk = _target_chunk_size(accessible_metrics, active_color)
    if run_length < target_chunk:
        return False

    phase_ratio = min(0.999999, max(0.0, current_time_s / float(DAY_DURATION_SECONDS)))
    current_zone = min(2, int(phase_ratio * 3.0))
    current_zone_gap = abs(color_zone_by_name.get(active_color, 1) - current_zone)
    current_avg_cost = _avg_access_cost(accessible_metrics, active_color)

    for color_name, metrics in accessible_metrics.items():
        if color_name == active_color:
            continue
        if metrics.get("topCount", 0.0) < 2.0 or metrics.get("wavePotential", 0.0) < 2.0:
            continue
        alt_zone_gap = abs(color_zone_by_name.get(color_name, 1) - current_zone)
        alt_avg_cost = _avg_access_cost(accessible_metrics, color_name)
        if alt_zone_gap <= current_zone_gap + 1 and alt_avg_cost <= current_avg_cost + 16.0:
            return True

    return run_length >= target_chunk + 2


def _accessible_wave_metrics(
    stacks: List[List[List[dict]]],
    remaining_by_color: Dict[str, int],
) -> Dict[str, Dict[str, float]]:
    metrics_by_color: Dict[str, Dict[str, float]] = {}
    for source_x in range(YARD_WIDTH):
        for source_z in range(YARD_LENGTH):
            stack = stacks[source_x][source_z]
            if not stack:
                continue
            container = stack[-1]
            color_name = container["color"]
            if remaining_by_color.get(color_name, 0) <= 0:
                continue
            metrics = metrics_by_color.setdefault(
                color_name,
                {
                    "topCount": 0.0,
                    "wavePotential": 0.0,
                    "widthCost": 0.0,
                },
            )
            metrics["topCount"] += 1.0
            metrics["wavePotential"] += float(_useful_wave_run_length(stack))
            metrics["widthCost"] += weighted_xy_cost(source_x, source_z, TRUCK_PICKUP_X, source_z)
    return metrics_by_color


def _pick_active_group_color(
    stacks: List[List[List[dict]]],
    remaining_by_color: Dict[str, int],
    *,
    current_time_s: float,
    color_zone_by_name: Dict[str, int],
    last_color: str | None,
    last_run_length: int,
    blocked_color: str | None = None,
) -> str | None:
    """Pick the next company batch using accessible wave potential, not yard clustering."""
    accessible_metrics = _accessible_wave_metrics(stacks, remaining_by_color)
    if not accessible_metrics:
        return None

    eligible_colors = [
        color_name
        for color_name in accessible_metrics.keys()
        if color_name != blocked_color
    ]
    if not eligible_colors:
        eligible_colors = list(accessible_metrics.keys())

    phase_ratio = min(0.999999, max(0.0, current_time_s / float(DAY_DURATION_SECONDS)))
    current_zone = min(2, int(phase_ratio * 3.0))

    return min(
        eligible_colors,
        key=lambda color_name: (
            abs(color_zone_by_name.get(color_name, 1) - current_zone),
            (
                max(0, last_run_length - _target_chunk_size(accessible_metrics, color_name) + 1)
                if color_name == last_color
                else 0
            ),
            max(0.0, remaining_by_color.get(color_name, 0) - accessible_metrics[color_name]["wavePotential"]),
            -accessible_metrics[color_name]["wavePotential"],
            -accessible_metrics[color_name]["topCount"],
            accessible_metrics[color_name]["widthCost"] / max(1.0, accessible_metrics[color_name]["topCount"]),
            -remaining_by_color.get(color_name, 0),
            color_name,
        ),
    )


def _preferred_color_order_from_access(stacks: List[List[List[dict]]], remaining_by_color: Dict[str, int]) -> List[str]:
    accessible_metrics = _accessible_wave_metrics(stacks, remaining_by_color)
    return sorted(
        remaining_by_color.keys(),
        key=lambda color_name: (
            max(0.0, remaining_by_color.get(color_name, 0) - accessible_metrics.get(color_name, {}).get("wavePotential", 0.0)),
            -(accessible_metrics.get(color_name, {}).get("wavePotential", 0.0)),
            -(accessible_metrics.get(color_name, {}).get("topCount", 0.0)),
            (
                accessible_metrics.get(color_name, {}).get("widthCost", 0.0)
                / max(1.0, accessible_metrics.get(color_name, {}).get("topCount", 0.0))
            ),
            -(remaining_by_color.get(color_name, 0)),
            color_name,
        ),
    )


def _color_zone_map(ordered_colors: List[str]) -> Dict[str, int]:
    if not ordered_colors:
        return {}
    if len(ordered_colors) == 1:
        return {ordered_colors[0]: 0}

    last_index = max(1, len(ordered_colors) - 1)
    return {
        color_name: min(2, round((index / last_index) * 2))
        for index, color_name in enumerate(ordered_colors)
    }


def _zone_window(zone_index: int) -> Tuple[float, float]:
    zone_length = DAY_DURATION_SECONDS / 3.0
    overlap = zone_length * 0.18
    start = zone_index * zone_length - (overlap if zone_index > 0 else 0.0)
    end = (zone_index + 1) * zone_length + (overlap if zone_index < 2 else 0.0)
    return max(0.0, start), min(float(DAY_DURATION_SECONDS), end)


def _target_load_start(
    *,
    color_name: str,
    trip_index: int,
    total_trips: int,
    color_zone_by_name: Dict[str, int],
) -> float:
    zone_index = color_zone_by_name.get(color_name, 1)
    window_start, window_end = _zone_window(zone_index)
    usable_start = window_start + (window_end - window_start) * 0.08
    usable_end = window_end - (window_end - window_start) * 0.08
    if total_trips <= 1:
        return (usable_start + usable_end) * 0.5
    fraction = trip_index / max(1, total_trips - 1)
    return usable_start + (usable_end - usable_start) * fraction


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
    total_by_color = dict(remaining_by_color)
    company_profiles = {color_name: _company_profile_for_color(color_name) for color_name in remaining_by_color}
    preferred_color_order = _preferred_color_order_from_access(working, remaining_by_color)
    color_zone_by_name = _color_zone_map(preferred_color_order)
    scheduled_trips_by_color: Dict[str, int] = {color_name: 0 for color_name in remaining_by_color}
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
    active_group_color: str | None = None

    while True:
        candidates = top_containers(working)
        if not candidates:
            break

        accessible_colors = {
            container["color"]
            for _source_x, _source_z, _source_y, container in candidates
            if remaining_by_color.get(container["color"], 0) > 0
        }
        if not accessible_colors:
            break

        last_color, current_run_length = _current_company_run(jobs)
        accessible_metrics = _accessible_wave_metrics(working, remaining_by_color)
        blocked_group_color = None
        if _should_rotate_company_chunk(
            active_color=active_group_color,
            last_color=last_color,
            run_length=current_run_length,
            current_time_s=crane_time,
            color_zone_by_name=color_zone_by_name,
            accessible_metrics=accessible_metrics,
        ):
            blocked_group_color = active_group_color
            active_group_color = None

        if (
            active_group_color is None
            or remaining_by_color.get(active_group_color, 0) <= 0
            or active_group_color not in accessible_colors
        ):
            active_group_color = _pick_active_group_color(
                working,
                remaining_by_color,
                current_time_s=crane_time,
                color_zone_by_name=color_zone_by_name,
                last_color=last_color,
                last_run_length=current_run_length,
                blocked_color=blocked_group_color,
            )
            if active_group_color is None:
                break

        group_candidates = [
            (source_x, source_z, source_y, container)
            for source_x, source_z, source_y, container in candidates
            if container["color"] == active_group_color
        ]
        if not group_candidates:
            # If the current company becomes buried under other groups, switch to
            # another accessible company instead of starving the rest of the day plan.
            active_group_color = None
            continue

        best_choice = None
        best_score = None
        for source_x, source_z, source_y, container in group_candidates:
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
                trip_index = scheduled_trips_by_color.get(container["color"], 0)
                target_load_start = _target_load_start(
                    color_name=container["color"],
                    trip_index=trip_index,
                    total_trips=total_by_color.get(container["color"], 1),
                    color_zone_by_name=color_zone_by_name,
                )
                zone_start, zone_end = _zone_window(color_zone_by_name.get(container["color"], 1))
                release_slack = (zone_end - zone_start) * 0.14
                release_time = max(zone_start, target_load_start - release_slack)
                tentative_load_start = max(crane_time, slot_free_at[slot_index], release_time)
                tentative_load_end = tentative_load_start + crane_task_seconds
                phase_ratio = min(0.999999, max(0.0, tentative_load_start / float(DAY_DURATION_SECONDS)))
                current_zone = min(2, int(phase_ratio * 3.0))
                phase_alignment_penalty = abs(color_zone_by_name.get(container["color"], 1) - current_zone) * 320.0
                schedule_spread_penalty = abs(tentative_load_start - target_load_start) * 0.12
                arrival_time, depart_time, lane_wait_seconds = estimate_truck_timing(
                    load_start=tentative_load_start,
                    load_end=tentative_load_end,
                    slot_index=slot_index,
                    lane_flow_free_at=lane_flow_free_at,
                )
                if depart_time > DAY_DURATION_SECONDS:
                    continue
                run_target = _target_chunk_size(accessible_metrics, container["color"])
                same_company_bonus = 0.0
                long_run_penalty = 0.0
                if jobs and jobs[-1]["containerColor"] == container["color"]:
                    if current_run_length < run_target:
                        same_company_bonus = -42.0
                    else:
                        overflow = current_run_length - run_target + 1
                        same_company_bonus = -12.0
                        long_run_penalty = float(overflow * overflow) * LONG_RUN_CONTINUATION_PENALTY
                company_switch_penalty = 0.0
                if jobs and jobs[-1]["containerColor"] != container["color"]:
                    previous_color = jobs[-1]["containerColor"]
                    previous_run_target = _target_chunk_size(accessible_metrics, previous_color)
                    company_switch_penalty += DAY_COMPANY_SWITCH_PENALTY
                    if remaining_by_color.get(previous_color, 0) > 0:
                        if current_run_length < previous_run_target:
                            company_switch_penalty += EARLY_SWITCH_PENALTY
                        else:
                            company_switch_penalty += DAY_INCOMPLETE_COMPANY_SWITCH_PENALTY * 0.18
                            if accessible_metrics.get(container["color"], {}).get("wavePotential", 0.0) >= 2.0:
                                company_switch_penalty -= ALTERNATE_WAVE_SWITCH_BONUS
                # Optimize for crane efficiency first: expensive lengthwise crane movement
                # is encoded in horizontal_weighted_cost (length axis weighted 10x).
                score = (
                    depart_time
                    + lane_wait_seconds * 2.0
                    + horizontal_weighted_cost * DAY_ENERGY_WEIGHT
                    + company_switch_penalty
                    + phase_alignment_penalty
                    + schedule_spread_penalty
                    + same_company_bonus
                    + long_run_penalty
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
        if remaining_by_color[color_name] <= 0:
            active_group_color = None
        scheduled_trips_by_color[color_name] = scheduled_trips_by_color.get(color_name, 0) + 1

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
