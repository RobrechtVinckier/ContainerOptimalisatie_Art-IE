"""Stack domain services and random yard generation."""

from __future__ import annotations

import colorsys
import random
import time
from typing import List, Mapping, Optional

from ..core.constants import (
    COLOR_ORDER,
    DEFAULT_CONTAINER_COUNT,
    LENGTH_COST_WEIGHT,
    TARGET_PATTERNS,
    TRUCK_LANE_WIDTH,
    YARD_HEIGHT,
    YARD_LENGTH,
    YARD_WIDTH,
    CONTAINER_METERS,
)


def _hsv_hex(h: float, s: float, v: float) -> str:
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


def _group_color_palette(group_count: int) -> List[str]:
    """Return deterministic, visually distinct colors for logical groups."""
    if group_count <= 0:
        return []

    palette: List[str] = []
    for index in range(group_count):
        if index < len(COLOR_ORDER):
            palette.append(COLOR_ORDER[index])
            continue

        # Golden-angle hue progression keeps colors spread apart as groups grow.
        offset = index - len(COLOR_ORDER)
        hue = (0.08 + offset * 0.618033988749895) % 1.0
        palette.append(_hsv_hex(hue, 0.68, 0.86))

    return palette


def yard_config_payload() -> dict:
    """Build static yard configuration payload for API clients."""
    return {
        "width": YARD_WIDTH,
        "length": YARD_LENGTH,
        "height": YARD_HEIGHT,
        "truckLaneWidth": TRUCK_LANE_WIDTH,
        "containerCount": DEFAULT_CONTAINER_COUNT,
        "lengthCostWeight": LENGTH_COST_WEIGHT,
        "containerMeters": CONTAINER_METERS,
    }


def create_empty_stacks() -> List[List[List[dict]]]:
    """Create an empty yard grid [x][z][stack]."""
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
    """Clone stacks into normalized dict payloads."""
    return [[[_normalize_container(container) for container in stack] for stack in columns] for columns in stacks]


def target_color_for_slot(x: int, z: int) -> str:
    """Return target slot color for a yard coordinate."""
    return TARGET_PATTERNS[z % len(TARGET_PATTERNS)][x]


DEFAULT_PLACEMENT_SCORE_WEIGHTS = {
    "cluster": 0.1,
    "top_mismatch": 1.8,
    "transitions": 1.6,
    "rehandles": 1.4,
    "impurity": 0.6,
    "buried_foreign": 2.6,
    "fragmentation": 0.1,
}


def resolve_placement_score_weights(score_weights: Optional[Mapping[str, float]] = None) -> dict:
    """Resolve placement-score weights with sane defaults and non-negative values."""
    resolved = dict(DEFAULT_PLACEMENT_SCORE_WEIGHTS)
    if score_weights is None:
        return resolved
    for key in resolved:
        value = score_weights.get(key)
        if isinstance(value, (int, float)):
            resolved[key] = max(0.0, float(value))
    return resolved


def placement_score_weights_from_algorithm_settings(settings: object | None) -> dict:
    """Map algorithm settings to placement-score weights used in summaries."""
    if settings is None:
        return dict(DEFAULT_PLACEMENT_SCORE_WEIGHTS)
    return resolve_placement_score_weights(
        {
            "cluster": getattr(settings, "lam", DEFAULT_PLACEMENT_SCORE_WEIGHTS["cluster"]),
            "top_mismatch": getattr(settings, "stackTopMismatchWeight", DEFAULT_PLACEMENT_SCORE_WEIGHTS["top_mismatch"]),
            "transitions": getattr(settings, "stackTransitionWeight", DEFAULT_PLACEMENT_SCORE_WEIGHTS["transitions"]),
            "rehandles": getattr(settings, "stackRehandleWeight", DEFAULT_PLACEMENT_SCORE_WEIGHTS["rehandles"]),
            "impurity": getattr(settings, "stackImpurityWeight", DEFAULT_PLACEMENT_SCORE_WEIGHTS["impurity"]),
            "buried_foreign": getattr(settings, "buriedForeignWeight", DEFAULT_PLACEMENT_SCORE_WEIGHTS["buried_foreign"]),
            "fragmentation": getattr(settings, "groupFragmentationWeight", DEFAULT_PLACEMENT_SCORE_WEIGHTS["fragmentation"]),
        }
    )


def summarize_stacks(stacks: List[List[List[dict]]], *, score_weights: Optional[Mapping[str, float]] = None) -> dict:
    """Summarize colors and placement score aligned with optimizer quality goals."""
    resolved_weights = resolve_placement_score_weights(score_weights)
    w_cluster = resolved_weights["cluster"]
    w_top_mismatch = resolved_weights["top_mismatch"]
    w_transitions = resolved_weights["transitions"]
    w_rehandles = resolved_weights["rehandles"]
    w_impurity = resolved_weights["impurity"]
    w_buried_foreign = resolved_weights["buried_foreign"]
    w_fragmentation = resolved_weights["fragmentation"]

    color_count = {color: 0 for color in COLOR_ORDER}
    # bounds[color] = [min_x, max_x, min_z, max_z]
    bounds: dict[str, list[int]] = {}
    color_stack_occupancy: dict[str, int] = {}
    total = 0
    top_mismatch_penalty = 0.0
    transition_penalty = 0.0
    rehandles_penalty = 0.0
    impurity_penalty = 0.0
    buried_foreign_penalty = 0.0
    max_top_mismatch = 0.0
    max_transitions = 0.0
    max_rehandles = 0.0
    max_impurity = 0.0
    max_buried_foreign = 0.0

    for x in range(YARD_WIDTH):
        for z in range(YARD_LENGTH):
            stack = stacks[x][z]
            n = len(stack)
            if n > 0:
                counts_in_stack: dict[str, int] = {}
                colors_seen = set()
                for container in stack:
                    color_name = container["color"]
                    counts_in_stack[color_name] = counts_in_stack.get(color_name, 0) + 1
                    colors_seen.add(color_name)
                top_color = stack[-1]["color"]
                top_run = 0
                for container in reversed(stack):
                    if container["color"] != top_color:
                        break
                    top_run += 1
                top_mismatch_penalty += float(n - top_run)
                impurity_penalty += float(n - max(counts_in_stack.values()))
                max_top_mismatch += float(max(0, n - 1))
                max_transitions += float(max(0, n - 1))
                max_impurity += float(max(0, n - 1))

                for color_name in colors_seen:
                    color_stack_occupancy[color_name] = color_stack_occupancy.get(color_name, 0) + 1

                max_rehandles += float(n * (n - 1) // 2)
                max_buried_foreign += float(n * (n - 1) * (n + 1) // 6)
                for lower_idx in range(n):
                    lower_color = stack[lower_idx]["color"]
                    for upper_idx in range(lower_idx + 1, n):
                        if stack[upper_idx]["color"] != lower_color:
                            rehandles_penalty += 1.0
                            buried_foreign_penalty += float(upper_idx - lower_idx)
                for idx in range(n - 1, 0, -1):
                    if stack[idx]["color"] != stack[idx - 1]["color"]:
                        transition_penalty += 1.0

            for container in stack:
                color_name = container["color"]
                if color_name not in color_count:
                    color_count[color_name] = 0
                color_count[color_name] += 1

                color_bounds = bounds.get(color_name)
                if color_bounds is None:
                    bounds[color_name] = [x, x, z, z]
                else:
                    if x < color_bounds[0]:
                        color_bounds[0] = x
                    if x > color_bounds[1]:
                        color_bounds[1] = x
                    if z < color_bounds[2]:
                        color_bounds[2] = z
                    if z > color_bounds[3]:
                        color_bounds[3] = z
                total += 1

    cluster_cost = 0.0
    active_groups = 0
    for color_name, count in color_count.items():
        if count <= 0:
            continue
        color_bounds = bounds[color_name]
        span_x = color_bounds[1] - color_bounds[0]
        span_z = color_bounds[3] - color_bounds[2]
        cluster_cost += 2.0 * span_z + 0.5 * span_x
        active_groups += 1

    fragmentation_penalty = 0.0
    max_fragmentation = 0.0
    total_stacks = YARD_WIDTH * YARD_LENGTH
    for color_name, count in color_count.items():
        if count <= 0:
            continue
        occupied = color_stack_occupancy.get(color_name, 0)
        if occupied > 0:
            fragmentation_penalty += float(occupied - 1)
        max_occ = min(int(count), total_stacks)
        if max_occ > 0:
            max_fragmentation += float(max_occ - 1)

    max_spread_per_group = 2.0 * (YARD_LENGTH - 1) + 0.5 * (YARD_WIDTH - 1)
    max_cluster_cost = active_groups * max_spread_per_group
    norm_cluster = (cluster_cost / max_cluster_cost) if max_cluster_cost > 0 else 0.0
    norm_top = (top_mismatch_penalty / max_top_mismatch) if max_top_mismatch > 0 else 0.0
    norm_transitions = (transition_penalty / max_transitions) if max_transitions > 0 else 0.0
    norm_rehandles = (rehandles_penalty / max_rehandles) if max_rehandles > 0 else 0.0
    norm_impurity = (impurity_penalty / max_impurity) if max_impurity > 0 else 0.0
    norm_buried = (buried_foreign_penalty / max_buried_foreign) if max_buried_foreign > 0 else 0.0
    norm_fragmentation = (fragmentation_penalty / max_fragmentation) if max_fragmentation > 0 else 0.0

    weighted_norm = (
        w_cluster * norm_cluster
        + w_top_mismatch * norm_top
        + w_transitions * norm_transitions
        + w_rehandles * norm_rehandles
        + w_impurity * norm_impurity
        + w_buried_foreign * norm_buried
        + w_fragmentation * norm_fragmentation
    )
    weight_total = (
        w_cluster
        + w_top_mismatch
        + w_transitions
        + w_rehandles
        + w_impurity
        + w_buried_foreign
        + w_fragmentation
    )
    if weight_total <= 0:
        score = 1.0
    else:
        score = max(0.0, min(1.0, 1.0 - (weighted_norm / weight_total)))
    in_target_slot = int(round(score * total))

    return {
        "colorCount": color_count,
        "total": total,
        "inTargetSlot": in_target_slot,
        "placementScore": score,
    }


def is_solved(stacks: List[List[List[dict]]]) -> bool:
    """Check whether every container matches the target slot color."""
    for x in range(YARD_WIDTH):
        for z in range(YARD_LENGTH):
            target = target_color_for_slot(x, z)
            for container in stacks[x][z]:
                if container["color"] != target:
                    return False
    return True


def random_configuration(
    seed: int | None = None,
    container_count: int = DEFAULT_CONTAINER_COUNT,
    *,
    yard_x: int = YARD_WIDTH,
    yard_y: int = YARD_LENGTH,
    yard_h: int = YARD_HEIGHT,
    groups: int | None = None,
    containers_per_group: int | None = None,
    min_containers_per_group: int | None = None,
    max_containers_per_group: int | None = None,
    score_weights: Optional[Mapping[str, float]] = None,
) -> dict:
    """Generate a random valid yard setup with deterministic seed support.

    Yard dimensions are fixed in this project (`YARD_WIDTH`, `YARD_LENGTH`,
    `YARD_HEIGHT`). The yard_* parameters are kept for compatibility and must
    match those fixed constants.
    """
    resolved_seed = int(seed if seed is not None else time.time_ns() % 1_000_000_000)
    rng = random.Random(resolved_seed)

    if yard_x != YARD_WIDTH or yard_y != YARD_LENGTH or yard_h != YARD_HEIGHT:
        raise ValueError(f"Yard dimensions are fixed to x={YARD_WIDTH}, y={YARD_LENGTH}, h={YARD_HEIGHT}")

    active_colors = list(COLOR_ORDER)
    if groups is not None:
        if groups < 1:
            raise ValueError("groups must be >= 1")
        max_capacity = YARD_WIDTH * YARD_LENGTH * YARD_HEIGHT
        if groups > max_capacity:
            raise ValueError(f"groups must be <= {max_capacity}")
        active_colors = _group_color_palette(groups)

    if containers_per_group is not None:
        if min_containers_per_group is not None or max_containers_per_group is not None:
            raise ValueError("Use either containersPerGroup OR min/max range, not both")
        min_containers_per_group = containers_per_group
        max_containers_per_group = containers_per_group

    if (min_containers_per_group is None) != (max_containers_per_group is None):
        raise ValueError("minContainersPerGroup and maxContainersPerGroup must be provided together")
    if min_containers_per_group is not None and groups is None:
        raise ValueError("groups is required when min/max containers per group is provided")

    max_capacity = YARD_WIDTH * YARD_LENGTH * YARD_HEIGHT
    if container_count > max_capacity:
        raise ValueError(
            f"Requested {container_count} containers exceeds yard capacity {max_capacity}"
        )
    if container_count < 1:
        raise ValueError("containerCount must be >= 1")

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

    grouped_colors: List[str] | None = None
    if groups is not None:
        counts_by_group: List[int] = []
        if min_containers_per_group is not None and max_containers_per_group is not None:
            if min_containers_per_group > max_containers_per_group:
                raise ValueError("minContainersPerGroup cannot be greater than maxContainersPerGroup")
            if min_containers_per_group < 1:
                raise ValueError("minContainersPerGroup must be >= 1")

            min_total = groups * min_containers_per_group
            max_total = groups * max_containers_per_group
            if container_count < min_total or container_count > max_total:
                raise ValueError(
                    f"containerCount={container_count} is outside feasible range [{min_total}, {max_total}] "
                    f"for groups={groups} and per-group range [{min_containers_per_group}, {max_containers_per_group}]"
                )

            remaining_total = container_count
            for idx in range(groups):
                groups_left_after = groups - idx - 1
                min_feasible = max(
                    min_containers_per_group,
                    remaining_total - groups_left_after * max_containers_per_group,
                )
                max_feasible = min(
                    max_containers_per_group,
                    remaining_total - groups_left_after * min_containers_per_group,
                )
                if min_feasible > max_feasible:
                    raise ValueError("Could not build valid group distribution with requested range")
                choice = rng.randint(min_feasible, max_feasible)
                counts_by_group.append(choice)
                remaining_total -= choice
        else:
            # Without explicit min/max, keep all logical groups active with >=1 container.
            if container_count < groups:
                raise ValueError("containerCount must be >= groups")
            remaining_total = container_count
            for idx in range(groups):
                groups_left_after = groups - idx - 1
                min_feasible = 1
                max_feasible = remaining_total - groups_left_after
                choice = rng.randint(min_feasible, max_feasible)
                counts_by_group.append(choice)
                remaining_total -= choice

        grouped_colors = []
        for group_index, count in enumerate(counts_by_group):
            color = active_colors[group_index]
            grouped_colors.extend([color] * count)
        rng.shuffle(grouped_colors)

    next_id = 1
    color_index = 0
    for x in range(YARD_WIDTH):
        for z in range(YARD_LENGTH):
            for _ in range(heights[x][z]):
                if grouped_colors is not None:
                    color = grouped_colors[color_index]
                    color_index += 1
                else:
                    color = active_colors[rng.randrange(len(active_colors))]
                stacks[x][z].append({"id": f"C{next_id:04d}", "color": color})
                next_id += 1

    return {
        "seed": resolved_seed,
        "stacks": stacks,
        "summary": summarize_stacks(stacks, score_weights=score_weights),
    }
