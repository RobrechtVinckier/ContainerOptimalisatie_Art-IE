from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple, Literal

try:
    from .state import Move, State, XY, travel_time
except ImportError:  # pragma: no cover - CLI fallback
    from state import Move, State, XY, travel_time

TabuMode = Literal["cid_edge", "edge", "edge_reverse", "combined"]
SelectionMode = Literal["best", "topk_best_nontabu", "topk_deterministic"]


@dataclass(frozen=True)
class Candidate:
    container_id: int
    src: XY
    dst: XY
    delta_cluster: float
    delta_time: float
    delta_energy: float
    score: float


@dataclass
class OptimizerConfig:
    # reproducibility
    seed: int = 0

    night_budget_s: float = 28800.0
    lam: float = 1.0
    energy_weight: float = 1.0
    energy_x_cost: float = 10.0
    energy_y_cost: float = 1.0
    energy_z_cost: float = 1.0

    # candidate generation controls
    top_groups: int = 5                 # consider groups with largest spread
    src_limit: int = 40                 # max source stacks to consider
    dst_limit_per_src: int = 30         # max destination stacks per source
    x_radius: int = 2                   # around group center x
    y_radius: int = 1                   # around group center y (if y_aware=True)
    y_aware: bool = True
    diversify_period: int = 0           # 0 disables periodic random destination injection
    diversify_random_dsts: int = 0      # per source when periodic injection triggers

    # tabu search controls
    tabu_len: int = 200
    tabu_iters: int = 1500
    tabu_mode: TabuMode = "combined"
    non_improving_penalty: float = 1.0
    top_k: int = 30
    selection_mode: SelectionMode = "topk_best_nontabu"
    plateau_iters: int = 120
    shake_enabled: bool = True

    # metrics
    metrics_sample_every: int = 50


@dataclass
class TabuMetrics:
    total_search_moves: int = 0
    unique_containers_moved: int = 0
    immediate_reversals: int = 0
    repeated_edges: int = 0
    best_cost_curve: List[Tuple[int, float]] = field(default_factory=list)


@dataclass(frozen=True)
class _RankedCandidate:
    candidate: Candidate
    tabu_score: float
    is_tabu: bool


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


def generate_candidate_moves(state: State, cfg: OptimizerConfig, iteration: Optional[int] = None) -> List[Candidate]:
    """
    Candidate restriction:
    a) pick groups with largest spread
    b) pick source stacks whose top container is in those groups
    c) pick destination stacks with free capacity near group center (x and optional y radius)
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
        center_y = int(round(cy))

        # prefer destinations near group center (weighted to match objective x/y coefficients).
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
        local_dsts.sort(
            key=lambda dst: (
                2.0 * abs(dst[0] - center_x) + 0.5 * abs(dst[1] - center_y),
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
            de = _move_energy_cost(state, src, dst, cfg)
            score = dt + cfg.lam * dcl + cfg.energy_weight * de
            candidates.append(Candidate(cid, src, dst, dcl, dt, de, score))

    # deterministic ordering for stable selection
    candidates.sort(
        key=lambda c: (c.score, c.delta_cluster, c.delta_time, c.delta_energy, c.container_id, c.src, c.dst)
    )
    return candidates


def greedy_plan(state: State, cfg: OptimizerConfig) -> List[Move]:
    moves: List[Move] = []
    while True:
        candidates = generate_candidate_moves(state, cfg, iteration=None)
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


def _tabu_score(candidate: Candidate, cfg: OptimizerConfig) -> float:
    penalty = cfg.non_improving_penalty if candidate.delta_cluster >= 0.0 else 0.0
    return candidate.score + penalty


def _is_tabu(
    candidate: Candidate,
    iteration: int,
    cfg: OptimizerConfig,
    tabu_cid_edge: Dict[Tuple[int, XY, XY], int],
    tabu_edge: Dict[Tuple[XY, XY], int],
    tabu_reverse_edge: Dict[Tuple[XY, XY], int],
) -> bool:
    if cfg.tabu_mode in ("cid_edge", "combined"):
        if tabu_cid_edge.get((candidate.container_id, candidate.src, candidate.dst), -1) > iteration:
            return True
    if cfg.tabu_mode in ("edge", "combined"):
        if tabu_edge.get((candidate.src, candidate.dst), -1) > iteration:
            return True
    if cfg.tabu_mode == "edge_reverse":
        if tabu_reverse_edge.get((candidate.src, candidate.dst), -1) > iteration:
            return True
    return False


def _register_tabu(
    candidate: Candidate,
    iteration: int,
    cfg: OptimizerConfig,
    tabu_cid_edge: Dict[Tuple[int, XY, XY], int],
    tabu_edge: Dict[Tuple[XY, XY], int],
    tabu_reverse_edge: Dict[Tuple[XY, XY], int],
) -> None:
    expire = iteration + cfg.tabu_len
    if cfg.tabu_mode in ("cid_edge", "combined"):
        tabu_cid_edge[(candidate.container_id, candidate.src, candidate.dst)] = expire
    if cfg.tabu_mode in ("edge", "combined"):
        tabu_edge[(candidate.src, candidate.dst)] = expire
    if cfg.tabu_mode == "edge_reverse":
        # record reverse edge to prevent immediate backtracking
        tabu_reverse_edge[(candidate.dst, candidate.src)] = expire


def _rank_candidates(
    state: State,
    cfg: OptimizerConfig,
    candidates: Sequence[Candidate],
    iteration: int,
    best_cost: float,
    allow_non_improving: bool,
    tabu_cid_edge: Dict[Tuple[int, XY, XY], int],
    tabu_edge: Dict[Tuple[XY, XY], int],
    tabu_reverse_edge: Dict[Tuple[XY, XY], int],
) -> List[_RankedCandidate]:
    cur_cost = state.cluster_cost()
    ranked: List[_RankedCandidate] = []

    for candidate in candidates:
        if state.time_used + candidate.delta_time > cfg.night_budget_s:
            continue
        if not allow_non_improving and candidate.delta_cluster >= 0.0:
            continue

        is_tabu = _is_tabu(
            candidate,
            iteration,
            cfg,
            tabu_cid_edge=tabu_cid_edge,
            tabu_edge=tabu_edge,
            tabu_reverse_edge=tabu_reverse_edge,
        )
        # aspiration: allow tabu if it beats global best cluster cost
        if is_tabu and not (cur_cost + candidate.delta_cluster < best_cost):
            continue

        ranked.append(_RankedCandidate(candidate=candidate, tabu_score=_tabu_score(candidate, cfg), is_tabu=is_tabu))

    ranked.sort(
        key=lambda rc: (
            rc.tabu_score,
            rc.candidate.delta_cluster,
            rc.candidate.delta_time,
            rc.candidate.container_id,
            rc.candidate.src,
            rc.candidate.dst,
        )
    )
    return ranked


def _select_ranked_candidate(
    ranked: Sequence[_RankedCandidate],
    cfg: OptimizerConfig,
    iteration: int,
    selection_mode: SelectionMode,
) -> Optional[_RankedCandidate]:
    if not ranked:
        return None

    if selection_mode == "best":
        return ranked[0]

    top_count = max(1, cfg.top_k)
    top = list(ranked[:top_count])
    if not top:
        return None

    if selection_mode == "topk_best_nontabu":
        for rc in top:
            if not rc.is_tabu:
                return rc
        return top[0]

    # topk_deterministic
    rng = random.Random(_mix_seed(cfg.seed, iteration, len(top)))
    return top[rng.randrange(len(top))]


def tabu_improve(state: State, cfg: OptimizerConfig, metrics: Optional[TabuMetrics] = None) -> Tuple[List[Move], State]:
    """
    Tabu search directly continues from current state, tracking best cluster_cost found.
    Tabu keying is configurable (container+edge, edge, reverse-edge, or combined).
    Aspiration: allow tabu if results in strictly better global best cluster_cost.
    """
    best_state = state.clone()
    best_cost = state.cluster_cost()
    best_moves: List[Move] = []

    tabu_cid_edge: Dict[Tuple[int, XY, XY], int] = {}
    tabu_edge: Dict[Tuple[XY, XY], int] = {}
    tabu_reverse_edge: Dict[Tuple[XY, XY], int] = {}

    moves: List[Move] = []
    plateau_count = 0

    moved_containers: Set[int] = set()
    seen_edges: Set[Tuple[XY, XY]] = set()
    immediate_reversals = 0
    repeated_edges = 0
    last_edge: Optional[Tuple[XY, XY]] = None
    sample_every = max(1, cfg.metrics_sample_every)
    last_iteration = -1

    if metrics is not None:
        metrics.total_search_moves = 0
        metrics.unique_containers_moved = 0
        metrics.immediate_reversals = 0
        metrics.repeated_edges = 0
        metrics.best_cost_curve = [(0, best_cost)]

    for it in range(cfg.tabu_iters):
        last_iteration = it
        candidates = generate_candidate_moves(state, cfg, iteration=it)
        if not candidates:
            break

        should_shake = cfg.shake_enabled and cfg.plateau_iters > 0 and plateau_count >= cfg.plateau_iters

        ranked: Optional[List[_RankedCandidate]] = None
        chosen_ranked: Optional[_RankedCandidate] = None
        if should_shake:
            ranked = _rank_candidates(
                state,
                cfg,
                candidates,
                it,
                best_cost=best_cost,
                allow_non_improving=True,
                tabu_cid_edge=tabu_cid_edge,
                tabu_edge=tabu_edge,
                tabu_reverse_edge=tabu_reverse_edge,
            )
            chosen_ranked = _select_ranked_candidate(ranked, cfg, it, selection_mode="topk_deterministic")
        else:
            ranked = _rank_candidates(
                state,
                cfg,
                candidates,
                it,
                best_cost=best_cost,
                allow_non_improving=False,
                tabu_cid_edge=tabu_cid_edge,
                tabu_edge=tabu_edge,
                tabu_reverse_edge=tabu_reverse_edge,
            )
            chosen_ranked = _select_ranked_candidate(ranked, cfg, it, selection_mode=cfg.selection_mode)
            if chosen_ranked is None:
                ranked = _rank_candidates(
                    state,
                    cfg,
                    candidates,
                    it,
                    best_cost=best_cost,
                    allow_non_improving=True,
                    tabu_cid_edge=tabu_cid_edge,
                    tabu_edge=tabu_edge,
                    tabu_reverse_edge=tabu_reverse_edge,
                )
                chosen_ranked = _select_ranked_candidate(ranked, cfg, it, selection_mode=cfg.selection_mode)

        if chosen_ranked is None:
            break
        chosen = chosen_ranked.candidate

        t0 = state.time_used
        moved_cid = state.apply_move(chosen.src, chosen.dst)
        t1 = state.time_used
        moves.append(Move(container_id=moved_cid, src=chosen.src, dst=chosen.dst, t_start=t0, t_end=t1))

        _register_tabu(
            chosen,
            it,
            cfg,
            tabu_cid_edge=tabu_cid_edge,
            tabu_edge=tabu_edge,
            tabu_reverse_edge=tabu_reverse_edge,
        )

        edge = (chosen.src, chosen.dst)
        moved_containers.add(moved_cid)
        if edge in seen_edges:
            repeated_edges += 1
        else:
            seen_edges.add(edge)
        if last_edge is not None and last_edge[0] == edge[1] and last_edge[1] == edge[0]:
            immediate_reversals += 1
        last_edge = edge

        if chosen.delta_cluster < 0.0:
            plateau_count = 0
        else:
            plateau_count += 1
        if should_shake:
            plateau_count = 0

        # update best
        cur_cost = state.cluster_cost()
        if cur_cost < best_cost:
            best_cost = cur_cost
            best_state = state.clone()
            best_moves = list(moves)
            plateau_count = 0

        if metrics is not None and (it + 1) % sample_every == 0:
            metrics.best_cost_curve.append((it + 1, best_cost))

    if metrics is not None:
        metrics.total_search_moves = len(moves)
        metrics.unique_containers_moved = len(moved_containers)
        metrics.immediate_reversals = immediate_reversals
        metrics.repeated_edges = repeated_edges
        final_x = last_iteration + 1 if last_iteration >= 0 else 0
        if not metrics.best_cost_curve or metrics.best_cost_curve[-1][0] != final_x:
            metrics.best_cost_curve.append((final_x, best_cost))

    return best_moves, best_state
