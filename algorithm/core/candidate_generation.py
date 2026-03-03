"""Candidate generation for greedy and tabu search."""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

try:
    from ..state import State, XY, travel_time
except ImportError:  # pragma: no cover - CLI fallback
    from state import State, XY, travel_time

from .optimizer_models import Candidate, OptimizerConfig


def _mix_seed(seed: int, *values: int) -> int:
    """Deterministic integer mixer for local RNG seeding."""
    x = (seed ^ 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    for v in values:
        x = (x * 6364136223846793005 + (v + 1442695040888963407)) & 0xFFFFFFFFFFFFFFFF
    return x


def _stack_top_height(state: State, xy: XY) -> int:
    """
    Top height index for a stack; empty stack is treated as 0 (ground level).
    """
    h = len(state.stack(xy)) - 1
    return h if h >= 0 else 0


def _move_energy_cost(state: State, src: XY, dst: XY, cfg: OptimizerConfig) -> float:
    """
    Electricity proxy for one move, using crane->src and src->dst motion:
    - width (x) is expensive
    - depth (y) and height (z) are cheaper
    """
    cx, cy = state.crane_pos
    sx, sy = src
    dx, dy = dst

    z_crane = _stack_top_height(state, state.crane_pos)
    z_src = _stack_top_height(state, src)
    # destination top after placing (before move destination height is len(stack))
    z_dst = len(state.stack(dst))

    ex = abs(cx - sx) + abs(sx - dx)
    ey = abs(cy - sy) + abs(sy - dy)
    ez = abs(z_crane - z_src) + abs(z_src - z_dst)
    return cfg.energy_x_cost * ex + cfg.energy_y_cost * ey + cfg.energy_z_cost * ez


def _destination_group_preference(state: State, group_index: int, dst: XY) -> int:
    """
    Hard preference for destination stack type:
    0) pure stack of same group
    1) empty stack
    2) mixed / other-group stack
    """
    stack = state.stack(dst)
    if not stack:
        return 1
    all_same = True
    for cid in stack:
        if state.group[cid] != group_index:
            all_same = False
            break
    if all_same:
        return 0
    return 2


def generate_candidate_moves(state: State, cfg: OptimizerConfig, iteration: Optional[int] = None) -> List[Candidate]:
    """
    Candidate restriction:
    a) pick groups with largest spread
    b) pick source stacks whose top container is in those groups
    c) pick destination stacks with free capacity near group center (x and optional y radius)
    """
    g_count = state.num_groups()
    if g_count <= 0:
        return []

    # pick largest-spread groups (deterministic tie-break by group id)
    group_order = sorted(range(g_count), key=lambda g: (-state.group_spread(g), g))
    focus_groups = set(group_order[: min(cfg.top_groups, g_count)])

    # enumerate source stacks with top container in focus group
    src_records: List[Tuple[Tuple[float, float, float, int, int], XY]] = []
    for x in range(state.X):
        for y in range(state.Y):
            top = state.top((x, y))
            if top is None:
                continue
            group_index = state.group[top]
            if group_index not in focus_groups:
                continue

            # Bound containers are most likely to reduce spread when moved.
            on_boundary = state.is_on_group_boundary(top, (x, y))
            cx, cy = state.group_center(group_index)
            center_x = int(round(cx))
            center_y = int(round(cy))
            dist_from_center = 2.0 * abs(x - center_x) + 0.5 * abs(y - center_y)
            impurity = state.stack_impurity_penalty((x, y))
            buried = state.stack_buried_foreign_penalty((x, y))
            priority = (
                0.0 if on_boundary else 1.0,
                -state.group_spread(group_index),
                -buried,
                -impurity,
                -dist_from_center,
                x,
                y,
            )
            src_records.append((priority, (x, y)))

    # deterministic source ordering: boundaries first, then spread and distance.
    src_records.sort(key=lambda item: item[0])
    srcs = [xy for _priority, xy in src_records]
    srcs = srcs[: cfg.src_limit]

    # precompute free destinations
    free: List[XY] = []
    for x in range(state.X):
        for y in range(state.Y):
            if len(state.stack((x, y))) < state.H:
                free.append((x, y))

    candidates: List[Candidate] = []
    for src in srcs:
        cid = state.top(src)
        if cid is None:
            continue
        group_index = state.group[cid]
        cx, cy = state.group_center(group_index)
        center_x = int(round(cx))
        center_y = int(round(cy))

        # prefer destinations near group center and compatible stacks.
        local_dsts = [
            xy
            for xy in free
            if xy != src
            and abs(xy[0] - center_x) <= cfg.x_radius
            and (not cfg.y_aware or abs(xy[1] - center_y) <= cfg.y_radius)
        ]
        if not local_dsts and cfg.y_aware:
            # fallback when y filter is too strict
            local_dsts = [xy for xy in free if xy != src and abs(xy[0] - center_x) <= cfg.x_radius]
        if not local_dsts:
            # robust fallback: keep search alive even when local radius is saturated
            local_dsts = [xy for xy in free if xy != src]
        local_dsts.sort(
            key=lambda dst: (
                _destination_group_preference(state, group_index, dst),
                2.0 * abs(dst[0] - center_x) + 0.5 * abs(dst[1] - center_y),
                state.stack_compatibility_penalty_for_group(group_index, dst),
                state.delta_stack_quality_for_move(
                    cid,
                    src,
                    dst,
                    top_mismatch_weight=cfg.stack_top_mismatch_weight,
                    rehandle_weight=cfg.stack_rehandle_weight,
                    impurity_weight=cfg.stack_impurity_weight,
                    buried_foreign_weight=cfg.buried_foreign_weight,
                ),
                travel_time(src, dst),
                dst[0],
                dst[1],
            )
        )
        local_dsts = local_dsts[: cfg.dst_limit_per_src]

        # deterministic periodic diversification: inject a few random legal destinations.
        inject_random = (
            iteration is not None
            and cfg.diversify_period > 0
            and cfg.diversify_random_dsts > 0
            and (iteration + 1) % cfg.diversify_period == 0
        )
        if inject_random:
            used = set(local_dsts)
            extras = [xy for xy in free if xy != src and xy not in used]
            if extras:
                rng = random.Random(_mix_seed(cfg.seed, iteration + 1, src[0], src[1], cid))
                rng.shuffle(extras)
                local_dsts.extend(extras[: cfg.diversify_random_dsts])

        for dst in local_dsts:
            if not state.can_move(src, dst):
                continue
            dt = state.move_time(src, dst)
            dcl = state.delta_cluster_cost_for_move(cid, src, dst)
            dtop = state.delta_stack_quality_for_move(
                cid,
                src,
                dst,
                top_mismatch_weight=1.0,
                rehandle_weight=0.0,
            )
            dreh = state.delta_stack_quality_for_move(
                cid,
                src,
                dst,
                top_mismatch_weight=0.0,
                rehandle_weight=1.0,
            )
            dimp = state.delta_stack_quality_for_move(
                cid,
                src,
                dst,
                top_mismatch_weight=0.0,
                rehandle_weight=0.0,
                impurity_weight=1.0,
                buried_foreign_weight=0.0,
            )
            dbury = state.delta_stack_quality_for_move(
                cid,
                src,
                dst,
                top_mismatch_weight=0.0,
                rehandle_weight=0.0,
                impurity_weight=0.0,
                buried_foreign_weight=1.0,
            )
            dfrag = state.delta_group_fragmentation_for_move(cid, src, dst)
            dstack = (
                cfg.stack_top_mismatch_weight * dtop
                + cfg.stack_rehandle_weight * dreh
                + cfg.stack_impurity_weight * dimp
                + cfg.buried_foreign_weight * dbury
            )
            dquality = cfg.lam * dcl + dstack + cfg.group_fragmentation_weight * dfrag
            de = _move_energy_cost(state, src, dst, cfg)
            operational = cfg.operational_weight * (dt + cfg.energy_weight * de)
            score = dquality + operational
            candidates.append(
                Candidate(
                    cid,
                    src,
                    dst,
                    dcl,
                    dt,
                    de,
                    score,
                    delta_quality=dquality,
                    delta_stack_top_mismatch=dtop,
                    delta_stack_rehandles=dreh,
                    delta_stack_impurity=dimp,
                    delta_buried_foreign=dbury,
                    delta_group_fragmentation=dfrag,
                    operational_cost=operational,
                )
            )

    # deterministic ordering for stable selection
    candidates.sort(
        key=lambda c: (
            c.delta_quality,
            c.operational_cost,
            c.score,
            c.delta_cluster,
            c.delta_time,
            c.delta_energy,
            c.container_id,
            c.src,
            c.dst,
        )
    )
    return candidates
