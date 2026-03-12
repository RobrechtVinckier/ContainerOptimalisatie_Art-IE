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


def _dominant_expensive_axis(cfg: OptimizerConfig) -> int:
    """Return axis index of the dominant horizontal energy cost: 0=x, 1=y."""
    return 0 if cfg.energy_x_cost >= cfg.energy_y_cost else 1


def _axis_delta(a: XY, b: XY, axis: int) -> int:
    return abs(a[axis] - b[axis])


def _axis_direction(a: XY, b: XY, axis: int) -> int:
    delta = b[axis] - a[axis]
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0


def _last_expensive_axis_direction(state: State, axis: int) -> int:
    if state.prev_crane_pos is None:
        return 0
    return _axis_direction(state.prev_crane_pos, state.crane_pos, axis)


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
    a) focus source stacks with the worst accessible stack-flow structure
    b) keep destinations local to the source to avoid unnecessary crane motion
    c) prefer moves that improve stack accessibility before any global layout compaction
    """
    g_count = state.num_groups()
    if g_count <= 0:
        return []

    expensive_axis = _dominant_expensive_axis(cfg)
    last_axis_direction = _last_expensive_axis_direction(state, expensive_axis)

    group_pressure = [0.0 for _ in range(g_count)]
    for x in range(state.X):
        for y in range(state.Y):
            top = state.top((x, y))
            if top is None:
                continue
            group_index = state.group[top]
            top_access = state.stack_top_group_mismatch_penalty((x, y))
            transitions = state.stack_group_transition_penalty((x, y))
            rehandles = state.stack_expected_rehandles_penalty((x, y))
            impurity = state.stack_impurity_penalty((x, y))
            buried = state.stack_buried_foreign_penalty((x, y))
            group_pressure[group_index] += (
                cfg.stack_top_mismatch_weight * top_access
                + cfg.stack_transition_weight * transitions
                + cfg.stack_rehandle_weight * rehandles
                + cfg.stack_impurity_weight * impurity
                + cfg.buried_foreign_weight * buried
            )

    group_order = sorted(range(g_count), key=lambda g: (-group_pressure[g], g))
    focus_groups = set(group_order[: min(cfg.top_groups, g_count)])

    # Enumerate source stacks with high accessible flow pressure.
    src_records: List[Tuple[Tuple[float, ...], XY]] = []
    for x in range(state.X):
        for y in range(state.Y):
            top = state.top((x, y))
            if top is None:
                continue
            group_index = state.group[top]
            if group_index not in focus_groups:
                continue

            top_access = state.stack_top_group_mismatch_penalty((x, y))
            transitions = state.stack_group_transition_penalty((x, y))
            impurity = state.stack_impurity_penalty((x, y))
            rehandles = state.stack_expected_rehandles_penalty((x, y))
            buried = state.stack_buried_foreign_penalty((x, y))
            structural_pressure = (
                cfg.stack_top_mismatch_weight * top_access
                + cfg.stack_transition_weight * transitions
                + cfg.stack_rehandle_weight * rehandles
                + cfg.stack_impurity_weight * impurity
                + cfg.buried_foreign_weight * buried
            )
            src_axis_direction = _axis_direction(state.crane_pos, (x, y), expensive_axis)
            reverses_recent_axis = 1 if (
                last_axis_direction != 0
                and src_axis_direction != 0
                and src_axis_direction != last_axis_direction
            ) else 0
            crane_axis_delta = _axis_delta(state.crane_pos, (x, y), expensive_axis)
            if cfg.max_expensive_axis_src_delta > 0 and crane_axis_delta > cfg.max_expensive_axis_src_delta:
                continue
            crane_reposition = travel_time(state.crane_pos, (x, y))
            priority = (
                reverses_recent_axis,
                crane_axis_delta,
                crane_reposition,
                -structural_pressure,
                -buried,
                -rehandles,
                -transitions,
                -top_access,
                -impurity,
                x,
                y,
            )
            src_records.append((priority, (x, y)))

    # deterministic source ordering: cheap crane motion first, then worst stack issues.
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

        # Keep destinations local to the current source rather than chasing a group center.
        local_dsts = [
            xy
            for xy in free
            if xy != src
            and abs(xy[0] - src[0]) <= cfg.x_radius
            and (not cfg.y_aware or abs(xy[1] - src[1]) <= cfg.y_radius)
        ]
        if not local_dsts and cfg.y_aware:
            local_dsts = [xy for xy in free if xy != src and abs(xy[0] - src[0]) <= cfg.x_radius]
        if not local_dsts:
            local_dsts = [xy for xy in free if xy != src]
        if cfg.max_expensive_axis_move_delta > 0:
            local_dsts = [
                xy
                for xy in local_dsts
                if _axis_delta(src, xy, expensive_axis) <= cfg.max_expensive_axis_move_delta
            ]
        if not local_dsts:
            continue
        local_dsts.sort(
            key=lambda dst: (
                _axis_delta(src, dst, expensive_axis),
                state.move_time(src, dst) + cfg.energy_weight * _move_energy_cost(state, src, dst, cfg),
                state.delta_stack_quality_for_move(
                    cid,
                    src,
                    dst,
                    top_mismatch_weight=cfg.stack_top_mismatch_weight,
                    transition_weight=cfg.stack_transition_weight,
                    rehandle_weight=cfg.stack_rehandle_weight,
                    impurity_weight=cfg.stack_impurity_weight,
                    buried_foreign_weight=cfg.buried_foreign_weight,
                ),
                state.stack_compatibility_penalty_for_group(group_index, dst),
                _destination_group_preference(state, group_index, dst),
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
                transition_weight=0.0,
                rehandle_weight=0.0,
            )
            dtrans = state.delta_stack_quality_for_move(
                cid,
                src,
                dst,
                top_mismatch_weight=0.0,
                transition_weight=1.0,
                rehandle_weight=0.0,
            )
            dreh = state.delta_stack_quality_for_move(
                cid,
                src,
                dst,
                top_mismatch_weight=0.0,
                transition_weight=0.0,
                rehandle_weight=1.0,
            )
            dimp = state.delta_stack_quality_for_move(
                cid,
                src,
                dst,
                top_mismatch_weight=0.0,
                transition_weight=0.0,
                rehandle_weight=0.0,
                impurity_weight=1.0,
                buried_foreign_weight=0.0,
            )
            dbury = state.delta_stack_quality_for_move(
                cid,
                src,
                dst,
                top_mismatch_weight=0.0,
                transition_weight=0.0,
                rehandle_weight=0.0,
                impurity_weight=0.0,
                buried_foreign_weight=1.0,
            )
            dfrag = state.delta_group_fragmentation_for_move(cid, src, dst)
            dstack = (
                cfg.stack_top_mismatch_weight * dtop
                + cfg.stack_transition_weight * dtrans
                + cfg.stack_rehandle_weight * dreh
                + cfg.stack_impurity_weight * dimp
                + cfg.buried_foreign_weight * dbury
            )
            dquality = cfg.lam * dcl + dstack + cfg.group_fragmentation_weight * dfrag
            de = _move_energy_cost(state, src, dst, cfg)
            travel_to_src_axis = _axis_delta(state.crane_pos, src, expensive_axis)
            loaded_axis_travel = _axis_delta(src, dst, expensive_axis)
            expensive_axis_travel = travel_to_src_axis + loaded_axis_travel
            expensive_axis_penalty = max(cfg.energy_x_cost, cfg.energy_y_cost) * float(expensive_axis_travel ** 2) * 0.45
            deadhead_axis_penalty = (
                max(cfg.energy_x_cost, cfg.energy_y_cost)
                * float(travel_to_src_axis ** 2)
                * cfg.expensive_axis_deadhead_weight
            )
            candidate_axis_direction = _axis_direction(state.crane_pos, dst, expensive_axis)
            reversal_axis_penalty = 0.0
            if (
                last_axis_direction != 0
                and candidate_axis_direction != 0
                and candidate_axis_direction != last_axis_direction
            ):
                reversal_axis_penalty = (
                    max(cfg.energy_x_cost, cfg.energy_y_cost)
                    * float(max(1, expensive_axis_travel) ** 2)
                    * cfg.expensive_axis_reversal_weight
                )
            operational = cfg.operational_weight * (
                dt
                + cfg.energy_weight * de
                + expensive_axis_penalty
                + deadhead_axis_penalty
                + reversal_axis_penalty
            )
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
                    delta_stack_transitions=dtrans,
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
