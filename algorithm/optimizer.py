from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from state import Move, State, XY, travel_time


@dataclass(frozen=True)
class Candidate:
    container_id: int
    src: XY
    dst: XY
    delta_cluster: float
    delta_time: float
    score: float


@dataclass
class OptimizerConfig:
    night_budget_s: float = 28800.0
    lam: float = 1.0

    # candidate generation controls
    top_groups: int = 5               # consider groups with largest spread
    src_limit: int = 40              # max source stacks to consider
    dst_limit_per_src: int = 30      # max destination stacks per source
    x_radius: int = 2                # around group center x

    # tabu search controls
    tabu_len: int = 200
    tabu_iters: int = 1500


def _all_xy(state: State) -> List[XY]:
    return [(x, y) for x in range(state.X) for y in range(state.Y)]


def generate_candidate_moves(state: State, cfg: OptimizerConfig) -> List[Candidate]:
    """
    Candidate restriction:
    a) pick groups with largest spread
    b) pick source stacks whose top container is in those groups
    c) pick destination stacks with free capacity near that group's center x (+/- x_radius)
    """
    G = state.num_groups()
    if G <= 0:
        return []

    # pick largest-spread groups (deterministic tie-break by group id)
    group_order = sorted(range(G), key=lambda g: (-state.group_spread(g), g))
    focus_groups = set(group_order[: min(cfg.top_groups, G)])

    # enumerate source stacks with top container in focus group
    srcs: List[XY] = []
    for x in range(state.X):
        for y in range(state.Y):
            top = state.top((x, y))
            if top is None:
                continue
            if state.group[top] in focus_groups:
                srcs.append((x, y))

    # deterministic source ordering: farthest spreads first via group's spread then coordinate
    srcs.sort(key=lambda xy: (-state.group_spread(state.group[state.top(xy)]), xy[0], xy[1]))  # type: ignore[arg-type]
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
        g = state.group[cid]
        cx, cy = state.group_center(g)
        center_x = int(round(cx))

        # prefer destinations near center_x, then near src, then stable ordering
        local_dsts = [xy for xy in free if xy != src and abs(xy[0] - center_x) <= cfg.x_radius]
        local_dsts.sort(key=lambda dst: (abs(dst[0] - center_x), travel_time(src, dst), dst[0], dst[1]))
        local_dsts = local_dsts[: cfg.dst_limit_per_src]

        for dst in local_dsts:
            if not state.can_move(src, dst):
                continue
            dt = state.move_time(src, dst)
            dcl = state.delta_cluster_cost_for_move(cid, src, dst)
            score = dt + cfg.lam * dcl
            candidates.append(Candidate(cid, src, dst, dcl, dt, score))

    # deterministic ordering for stable selection
    candidates.sort(key=lambda c: (c.score, c.delta_cluster, c.delta_time, c.container_id, c.src, c.dst))
    return candidates


def greedy_plan(state: State, cfg: OptimizerConfig) -> List[Move]:
    moves: List[Move] = []
    while True:
        candidates = generate_candidate_moves(state, cfg)
        if not candidates:
            break

        best: Optional[Candidate] = None
        for c in candidates:
            # within remaining budget?
            if state.time_used + c.delta_time > cfg.night_budget_s:
                continue
            best = c
            break

        if best is None:
            break

        # "no zinvolle moves": stop if best does not improve clustering (delta_cluster >= 0)
        if best.delta_cluster >= 0.0:
            break

        t0 = state.time_used
        moved_cid = state.apply_move(best.src, best.dst)
        t1 = state.time_used
        moves.append(Move(container_id=moved_cid, src=best.src, dst=best.dst, t_start=t0, t_end=t1))

    return moves


def tabu_improve(state: State, cfg: OptimizerConfig) -> Tuple[List[Move], State]:
    """
    Tabu search directly continues from current state, tracking best cluster_cost found.
    Tabu key: (container_id, src, dst)
    Aspiration: allow tabu if results in strictly better global best cluster_cost.
    """
    best_state = state.clone()
    best_cost = state.cluster_cost()
    best_moves: List[Move] = []

    tabu: Dict[Tuple[int, XY, XY], int] = {}  # key -> expiration iteration

    moves: List[Move] = []
    for it in range(cfg.tabu_iters):
        candidates = generate_candidate_moves(state, cfg)
        if not candidates:
            break

        chosen: Optional[Candidate] = None
        chosen_is_tabu = False

        for c in candidates:
            if state.time_used + c.delta_time > cfg.night_budget_s:
                continue

            key = (c.container_id, c.src, c.dst)
            is_tabu = key in tabu and tabu[key] > it
            # aspiration: if new cost beats global best, allow even if tabu
            new_cost = state.cluster_cost() + c.delta_cluster
            if is_tabu and not (new_cost < best_cost):
                continue

            chosen = c
            chosen_is_tabu = is_tabu
            break

        if chosen is None:
            break

        t0 = state.time_used
        moved_cid = state.apply_move(chosen.src, chosen.dst)
        t1 = state.time_used
        moves.append(Move(container_id=moved_cid, src=chosen.src, dst=chosen.dst, t_start=t0, t_end=t1))

        # register tabu
        key = (chosen.container_id, chosen.src, chosen.dst)
        tabu[key] = it + cfg.tabu_len

        # update best
        cur_cost = state.cluster_cost()
        if cur_cost < best_cost:
            best_cost = cur_cost
            best_state = state.clone()
            best_moves = list(moves)

    return best_moves, best_state