"""Greedy and tabu search routines for yard optimization."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from functools import cmp_to_key
import random
from typing import Deque, Dict, List, Optional, Sequence, Set, Tuple

try:
    from ..state import Move, State, XY
except ImportError:  # pragma: no cover - CLI fallback
    from state import Move, State, XY

from .candidate_generation import _mix_seed, generate_candidate_moves
from .optimizer_models import Candidate, OptimizerConfig, SelectionMode, TabuMetrics, _RankedCandidate


@dataclass(frozen=True)
class _EliteEntry:
    objective: float
    signature: Tuple[Tuple[int, ...], ...]
    state: State
    moves: List[Move]


def _objective_cost(state: State, cfg: OptimizerConfig) -> float:
    """Global objective used by search: low-cost stack flow with minor layout pressure."""
    cluster = cfg.lam * state.cluster_cost()
    stack_quality = state.total_stack_quality_cost(
        top_mismatch_weight=cfg.stack_top_mismatch_weight,
        transition_weight=cfg.stack_transition_weight,
        rehandle_weight=cfg.stack_rehandle_weight,
        impurity_weight=cfg.stack_impurity_weight,
        buried_foreign_weight=cfg.buried_foreign_weight,
    )
    fragmentation = cfg.group_fragmentation_weight * state.total_group_fragmentation_cost()
    return cluster + stack_quality + fragmentation


def _candidate_quality(candidate: Candidate, cfg: OptimizerConfig) -> float:
    # Keep compatibility with older candidate payloads that may miss delta_quality.
    if hasattr(candidate, "delta_quality"):
        quality = float(candidate.delta_quality)
        if quality != 0.0:
            return quality
        if (
            candidate.delta_cluster != 0.0
            and candidate.delta_stack_top_mismatch == 0.0
            and candidate.delta_stack_rehandles == 0.0
            and candidate.delta_stack_impurity == 0.0
            and candidate.delta_buried_foreign == 0.0
            and candidate.delta_group_fragmentation == 0.0
        ):
            return cfg.lam * candidate.delta_cluster
        return quality
    return cfg.lam * candidate.delta_cluster


def _candidate_operational(candidate: Candidate, cfg: OptimizerConfig) -> float:
    if hasattr(candidate, "operational_cost"):
        operational = float(candidate.operational_cost)
        if operational != 0.0:
            return operational
        if candidate.delta_time != 0.0 or candidate.delta_energy != 0.0:
            return cfg.operational_weight * (candidate.delta_time + cfg.energy_weight * candidate.delta_energy)
        return operational
    return cfg.operational_weight * (candidate.delta_time + cfg.energy_weight * candidate.delta_energy)


def _effective_quality(quality: float, operational: float, cfg: OptimizerConfig) -> float:
    """Blend quality and operational cost on a comparable scale."""
    normalizer = max(1e-9, cfg.operational_normalizer)
    return quality + (operational / normalizer)


def _candidate_effective_quality(candidate: Candidate, cfg: OptimizerConfig) -> float:
    return _effective_quality(_candidate_quality(candidate, cfg), _candidate_operational(candidate, cfg), cfg)


def _candidate_structural(candidate: Candidate, cfg: OptimizerConfig) -> float:
    """Stack-structure-specific part of quality (group purity / burial / fragmentation)."""
    return (
        cfg.stack_top_mismatch_weight * candidate.delta_stack_top_mismatch
        + cfg.stack_transition_weight * candidate.delta_stack_transitions
        + cfg.stack_rehandle_weight * candidate.delta_stack_rehandles
        + cfg.stack_impurity_weight * candidate.delta_stack_impurity
        + cfg.buried_foreign_weight * candidate.delta_buried_foreign
        + cfg.group_fragmentation_weight * candidate.delta_group_fragmentation
    )


def _compare_candidate_lexicographic(a: Candidate, b: Candidate, cfg: OptimizerConfig) -> int:
    """Compare candidates by blended efficiency, then detailed tie-breakers."""
    qa = _candidate_quality(a, cfg)
    qb = _candidate_quality(b, cfg)
    ea = _effective_quality(qa, _candidate_operational(a, cfg), cfg)
    eb = _effective_quality(qb, _candidate_operational(b, cfg), cfg)
    eps = max(0.0, cfg.quality_tie_eps)
    if abs(ea - eb) > eps:
        return -1 if ea < eb else 1
    if abs(qa - qb) > eps:
        return -1 if qa < qb else 1

    sa = _candidate_structural(a, cfg)
    sb = _candidate_structural(b, cfg)
    if sa < sb:
        return -1
    if sa > sb:
        return 1

    oa = _candidate_operational(a, cfg)
    ob = _candidate_operational(b, cfg)
    if oa < ob:
        return -1
    if oa > ob:
        return 1

    if qa < qb:
        return -1
    if qa > qb:
        return 1
    if a.container_id != b.container_id:
        return -1 if a.container_id < b.container_id else 1
    if a.src != b.src:
        return -1 if a.src < b.src else 1
    if a.dst != b.dst:
        return -1 if a.dst < b.dst else 1
    return 0


def _compare_ranked_lexicographic(a: _RankedCandidate, b: _RankedCandidate, cfg: OptimizerConfig) -> int:
    qa = a.quality_score
    qb = b.quality_score
    ea = _effective_quality(qa, a.operational_score, cfg)
    eb = _effective_quality(qb, b.operational_score, cfg)
    eps = max(0.0, cfg.quality_tie_eps)
    if abs(ea - eb) > eps:
        return -1 if ea < eb else 1
    if abs(qa - qb) > eps:
        return -1 if qa < qb else 1

    sa = _candidate_structural(a.candidate, cfg)
    sb = _candidate_structural(b.candidate, cfg)
    if sa < sb:
        return -1
    if sa > sb:
        return 1

    if a.operational_score < b.operational_score:
        return -1
    if a.operational_score > b.operational_score:
        return 1
    if qa < qb:
        return -1
    if qa > qb:
        return 1

    ca = a.candidate
    cb = b.candidate
    if ca.container_id != cb.container_id:
        return -1 if ca.container_id < cb.container_id else 1
    if ca.src != cb.src:
        return -1 if ca.src < cb.src else 1
    if ca.dst != cb.dst:
        return -1 if ca.dst < cb.dst else 1
    return 0


def _state_signature(state: State) -> Tuple[Tuple[int, ...], ...]:
    return tuple(tuple(state.yard[x][y]) for x in range(state.X) for y in range(state.Y))


def _push_elite_state(
    elites: List[_EliteEntry],
    state: State,
    moves: Sequence[Move],
    objective: float,
    cfg: OptimizerConfig,
) -> None:
    if cfg.elite_pool_size <= 0:
        return
    signature = _state_signature(state)
    for idx, entry in enumerate(elites):
        if entry.signature == signature:
            if objective + 1e-12 < entry.objective:
                elites[idx] = _EliteEntry(objective=objective, signature=signature, state=state.clone(), moves=list(moves))
            break
    else:
        elites.append(_EliteEntry(objective=objective, signature=signature, state=state.clone(), moves=list(moves)))

    elites.sort(key=lambda item: (item.objective, item.signature))
    if len(elites) > cfg.elite_pool_size:
        del elites[cfg.elite_pool_size :]


def greedy_plan(state: State, cfg: OptimizerConfig) -> List[Move]:
    """Build a greedy improving move sequence within the night budget."""
    moves: List[Move] = []
    while True:
        candidates = generate_candidate_moves(state, cfg, iteration=None)
        if not candidates:
            break

        feasible = [candidate for candidate in candidates if state.time_used + candidate.delta_time <= cfg.night_budget_s]
        if not feasible:
            break
        feasible.sort(key=cmp_to_key(lambda a, b: _compare_candidate_lexicographic(a, b, cfg)))
        best = feasible[0]

        # No useful move for configured quality + operational efficiency.
        if _candidate_effective_quality(best, cfg) >= 0.0:
            break

        t0 = state.time_used
        moved_cid = state.apply_move(best.src, best.dst)
        t1 = state.time_used
        moves.append(Move(container_id=moved_cid, src=best.src, dst=best.dst, t_start=t0, t_end=t1))

    return moves


def _tabu_score(candidate: Candidate, cfg: OptimizerConfig, extra_penalty: float = 0.0) -> float:
    quality = _candidate_quality(candidate, cfg) + extra_penalty
    effective = _effective_quality(quality, _candidate_operational(candidate, cfg), cfg)
    if effective >= 0.0:
        quality += cfg.non_improving_penalty
    return quality


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
    *,
    tabu_len: Optional[int] = None,
) -> None:
    expire = iteration + (cfg.tabu_len if tabu_len is None else tabu_len)
    if cfg.tabu_mode in ("cid_edge", "combined"):
        tabu_cid_edge[(candidate.container_id, candidate.src, candidate.dst)] = expire
    if cfg.tabu_mode in ("edge", "combined"):
        tabu_edge[(candidate.src, candidate.dst)] = expire
    if cfg.tabu_mode == "edge_reverse":
        # record reverse edge to prevent immediate backtracking
        tabu_reverse_edge[(candidate.dst, candidate.src)] = expire


def _compress_canceling_move_pairs(moves: Sequence[Move]) -> List[Move]:
    """Remove adjacent inverse moves of the same container.

    Why:
    These pairs return the yard to the same exact state and are visually/operationally
    useless in the exported night plan.
    """
    reduced: List[Move] = []
    for move in moves:
        if reduced:
            prev = reduced[-1]
            if (
                prev.container_id == move.container_id
                and prev.src == move.dst
                and prev.dst == move.src
            ):
                reduced.pop()
                continue
        reduced.append(move)
    return reduced


def _compress_same_container_runs(moves: Sequence[Move]) -> List[Move]:
    """Collapse consecutive moves of the same container into one net move."""
    reduced: List[Move] = []
    idx = 0
    while idx < len(moves):
        start = idx
        cid = moves[idx].container_id
        while idx + 1 < len(moves) and moves[idx + 1].container_id == cid:
            idx += 1
        end = idx

        first = moves[start]
        last = moves[end]
        if first.src != last.dst:
            reduced.append(
                Move(
                    container_id=cid,
                    src=first.src,
                    dst=last.dst,
                    t_start=first.t_start,
                    t_end=last.t_end,
                )
            )
        idx += 1
    return reduced


def _compress_redundant_sequences(moves: Sequence[Move]) -> List[Move]:
    """Apply deterministic local reductions until sequence reaches a fixed point."""
    current = list(moves)
    max_passes = max(4, len(current) * 2 + 2)
    for _ in range(max_passes):
        next_seq = _compress_canceling_move_pairs(current)
        next_seq = _compress_same_container_runs(next_seq)
        # Second pass removes newly exposed adjacent inverses after run collapsing.
        next_seq = _compress_canceling_move_pairs(next_seq)

        if len(next_seq) == len(current):
            unchanged = True
            for i in range(len(current)):
                a = current[i]
                b = next_seq[i]
                if a.container_id != b.container_id or a.src != b.src or a.dst != b.dst:
                    unchanged = False
                    break
            if unchanged:
                return next_seq
        current = next_seq
    return current


def _replay_moves(start_state: State, moves: Sequence[Move]) -> Tuple[List[Move], State] | None:
    """Replay move list on a cloned start state to rebuild consistent timings."""
    replay = start_state.clone()
    rebuilt: List[Move] = []
    for move in moves:
        if not replay.can_move(move.src, move.dst):
            return None
        top_before = replay.top(move.src)
        if top_before != move.container_id:
            return None
        t0 = replay.time_used
        moved_cid = replay.apply_move(move.src, move.dst)
        t1 = replay.time_used
        if moved_cid != move.container_id:
            return None
        rebuilt.append(Move(container_id=moved_cid, src=move.src, dst=move.dst, t_start=t0, t_end=t1))
    return rebuilt, replay


def _rank_candidates(
    state: State,
    cfg: OptimizerConfig,
    candidates: Sequence[Candidate],
    iteration: int,
    best_objective: float,
    allow_non_improving: bool,
    tabu_cid_edge: Dict[Tuple[int, XY, XY], int],
    tabu_edge: Dict[Tuple[XY, XY], int],
    tabu_reverse_edge: Dict[Tuple[XY, XY], int],
    edge_frequency: Optional[Dict[Tuple[XY, XY], int]] = None,
    stack_frequency: Optional[Dict[XY, int]] = None,
    container_frequency: Optional[Dict[int, int]] = None,
    *,
    ignore_tabu: bool = False,
) -> List[_RankedCandidate]:
    cur_objective = _objective_cost(state, cfg)
    ranked: List[_RankedCandidate] = []

    for candidate in candidates:
        if state.time_used + candidate.delta_time > cfg.night_budget_s:
            continue
        quality_delta = _candidate_quality(candidate, cfg)
        operational = _candidate_operational(candidate, cfg)
        effective_quality = _effective_quality(quality_delta, operational, cfg)
        if not allow_non_improving and effective_quality >= 0.0:
            continue

        frequency_penalty = 0.0
        if edge_frequency is not None and cfg.frequency_edge_weight != 0.0:
            frequency_penalty += cfg.frequency_edge_weight * edge_frequency.get((candidate.src, candidate.dst), 0)
        if stack_frequency is not None and cfg.frequency_stack_weight != 0.0:
            frequency_penalty += cfg.frequency_stack_weight * (
                stack_frequency.get(candidate.src, 0) + stack_frequency.get(candidate.dst, 0)
            )
        if container_frequency is not None and cfg.frequency_container_weight != 0.0:
            frequency_penalty += cfg.frequency_container_weight * container_frequency.get(candidate.container_id, 0)

        is_tabu = _is_tabu(
            candidate,
            iteration,
            cfg,
            tabu_cid_edge=tabu_cid_edge,
            tabu_edge=tabu_edge,
            tabu_reverse_edge=tabu_reverse_edge,
        )
        # aspiration: allow tabu if it improves global-best objective.
        if not ignore_tabu and is_tabu and not (cur_objective + quality_delta < best_objective):
            continue

        quality_score = _tabu_score(candidate, cfg, extra_penalty=frequency_penalty)
        ranked.append(
            _RankedCandidate(
                candidate=Candidate(
                    candidate.container_id,
                    candidate.src,
                    candidate.dst,
                    candidate.delta_cluster,
                    candidate.delta_time,
                    candidate.delta_energy,
                    candidate.score,
                    delta_quality=candidate.delta_quality,
                    delta_stack_top_mismatch=candidate.delta_stack_top_mismatch,
                    delta_stack_transitions=candidate.delta_stack_transitions,
                    delta_stack_rehandles=candidate.delta_stack_rehandles,
                    delta_stack_impurity=candidate.delta_stack_impurity,
                    delta_buried_foreign=candidate.delta_buried_foreign,
                    delta_group_fragmentation=candidate.delta_group_fragmentation,
                    operational_cost=operational,
                    frequency_penalty=frequency_penalty,
                ),
                quality_score=quality_score,
                operational_score=operational,
                is_tabu=is_tabu,
            )
        )

    ranked.sort(key=cmp_to_key(lambda a, b: _compare_ranked_lexicographic(a, b, cfg)))
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
        for ranked_candidate in top:
            if not ranked_candidate.is_tabu:
                return ranked_candidate
        return top[0]

    # topk_deterministic
    rng = random.Random(_mix_seed(cfg.seed, iteration, len(top)))
    return top[rng.randrange(len(top))]


def _select_path_relink_candidate(
    ranked: Sequence[_RankedCandidate],
    target_state: State,
    cfg: OptimizerConfig,
) -> Optional[_RankedCandidate]:
    """Pick a move that brings containers closer to target elite placements."""
    if not ranked:
        return None
    top_count = max(1, cfg.top_k)
    top = list(ranked[:top_count])
    best: Optional[_RankedCandidate] = None
    best_gain: Optional[int] = None
    for ranked_candidate in top:
        candidate = ranked_candidate.candidate
        target_xy = target_state.pos[candidate.container_id]
        before = abs(candidate.src[0] - target_xy[0]) + abs(candidate.src[1] - target_xy[1])
        after = abs(candidate.dst[0] - target_xy[0]) + abs(candidate.dst[1] - target_xy[1])
        gain = before - after
        if gain <= 0:
            continue
        if best is None or gain > int(best_gain or 0):
            best = ranked_candidate
            best_gain = gain
            continue
        if gain == best_gain and _compare_ranked_lexicographic(ranked_candidate, best, cfg) < 0:
            best = ranked_candidate
            best_gain = gain
    return best


def tabu_improve(state: State, cfg: OptimizerConfig, metrics: Optional[TabuMetrics] = None) -> Tuple[List[Move], State]:
    """
    Tabu search with aspiration, frequency memory, and optional elite-based diversification.

    The optimized objective is:
      lam * cluster_cost + weighted_stack_quality
    """
    search_start = state.clone()
    best_state = state.clone()
    best_objective = _objective_cost(state, cfg)
    best_moves: List[Move] = []

    current_tabu_len = cfg.tabu_len
    if cfg.reactive_tabu_enabled:
        low = min(cfg.tabu_len_min, cfg.tabu_len_max)
        high = max(cfg.tabu_len_min, cfg.tabu_len_max)
        current_tabu_len = max(low, min(high, cfg.tabu_len))

    tabu_cid_edge: Dict[Tuple[int, XY, XY], int] = {}
    tabu_edge: Dict[Tuple[XY, XY], int] = {}
    tabu_reverse_edge: Dict[Tuple[XY, XY], int] = {}
    edge_frequency: Dict[Tuple[XY, XY], int] = {}
    stack_frequency: Dict[XY, int] = {}
    container_frequency: Dict[int, int] = {}

    moves: List[Move] = []
    plateau_count = 0

    moved_containers: Set[int] = set()
    seen_edges: Set[Tuple[XY, XY]] = set()
    immediate_reversals = 0
    repeated_edges = 0
    last_edge: Optional[Tuple[XY, XY]] = None
    sample_every = max(1, cfg.metrics_sample_every)
    last_iteration = -1
    stop_reason = "iters_exhausted"

    window_size = max(2, cfg.tabu_reactive_window)
    reversals_window: Deque[int] = deque(maxlen=window_size)
    repeated_window: Deque[int] = deque(maxlen=window_size)
    improving_window: Deque[int] = deque(maxlen=window_size)

    elites: List[_EliteEntry] = []
    _push_elite_state(elites, state, moves, best_objective, cfg)
    restart_count = 0
    relink_steps_applied = 0
    relink_target: Optional[State] = None
    relink_remaining = 0

    if metrics is not None:
        metrics.total_search_moves = 0
        metrics.unique_containers_moved = 0
        metrics.immediate_reversals = 0
        metrics.repeated_edges = 0
        metrics.best_cost_curve = [(0, best_state.cluster_cost())]
        metrics.tabu_len_curve = [(0, current_tabu_len)]
        metrics.stop_reason = ""
        metrics.restart_count = 0
        metrics.relink_steps_applied = 0

    for it in range(cfg.tabu_iters):
        last_iteration = it
        if (
            cfg.elite_restart_enabled
            and cfg.plateau_iters > 0
            and plateau_count >= cfg.plateau_iters
            and elites
        ):
            restart_idx = int(_mix_seed(cfg.seed, it, restart_count, len(elites)) % len(elites))
            restart_entry = elites[restart_idx]
            state = restart_entry.state.clone()
            moves = list(restart_entry.moves)
            plateau_count = 0
            restart_count += 1

            relink_target = None
            relink_remaining = 0
            if cfg.path_relink_enabled and len(elites) >= 2:
                offset = int(_mix_seed(cfg.seed, it, restart_count, len(elites) + 7) % (len(elites) - 1))
                target_idx = (restart_idx + 1 + offset) % len(elites)
                relink_target = elites[target_idx].state
                relink_remaining = max(0, cfg.path_relink_steps)

        candidates = generate_candidate_moves(state, cfg, iteration=it)
        if not candidates:
            stop_reason = "no_candidates"
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
                best_objective=best_objective,
                allow_non_improving=True,
                tabu_cid_edge=tabu_cid_edge,
                tabu_edge=tabu_edge,
                tabu_reverse_edge=tabu_reverse_edge,
                edge_frequency=edge_frequency,
                stack_frequency=stack_frequency,
                container_frequency=container_frequency,
            )
            chosen_ranked = _select_ranked_candidate(ranked, cfg, it, selection_mode="topk_deterministic")
        else:
            ranked = _rank_candidates(
                state,
                cfg,
                candidates,
                it,
                best_objective=best_objective,
                allow_non_improving=False,
                tabu_cid_edge=tabu_cid_edge,
                tabu_edge=tabu_edge,
                tabu_reverse_edge=tabu_reverse_edge,
                edge_frequency=edge_frequency,
                stack_frequency=stack_frequency,
                container_frequency=container_frequency,
            )
            chosen_ranked = _select_ranked_candidate(ranked, cfg, it, selection_mode=cfg.selection_mode)
            if chosen_ranked is None:
                ranked = _rank_candidates(
                    state,
                    cfg,
                    candidates,
                    it,
                    best_objective=best_objective,
                    allow_non_improving=True,
                    tabu_cid_edge=tabu_cid_edge,
                    tabu_edge=tabu_edge,
                    tabu_reverse_edge=tabu_reverse_edge,
                    edge_frequency=edge_frequency,
                    stack_frequency=stack_frequency,
                    container_frequency=container_frequency,
                )
                chosen_ranked = _select_ranked_candidate(ranked, cfg, it, selection_mode=cfg.selection_mode)

        if chosen_ranked is None and cfg.tabu_mode != "edge_reverse":
            ranked = _rank_candidates(
                state,
                cfg,
                candidates,
                it,
                best_objective=best_objective,
                allow_non_improving=True,
                tabu_cid_edge=tabu_cid_edge,
                tabu_edge=tabu_edge,
                tabu_reverse_edge=tabu_reverse_edge,
                edge_frequency=edge_frequency,
                stack_frequency=stack_frequency,
                container_frequency=container_frequency,
                ignore_tabu=True,
            )
            chosen_ranked = _select_ranked_candidate(ranked, cfg, it, selection_mode="best")

        if chosen_ranked is None:
            stop_reason = "no_admissible_candidate"
            break

        if relink_target is not None and relink_remaining > 0:
            relink_pick = _select_path_relink_candidate(ranked or (), relink_target, cfg)
            if relink_pick is not None:
                chosen_ranked = relink_pick
                relink_steps_applied += 1
            relink_remaining -= 1
            if relink_remaining <= 0:
                relink_target = None

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
            tabu_len=current_tabu_len,
        )

        edge = (chosen.src, chosen.dst)
        edge_frequency[edge] = edge_frequency.get(edge, 0) + 1
        stack_frequency[chosen.src] = stack_frequency.get(chosen.src, 0) + 1
        stack_frequency[chosen.dst] = stack_frequency.get(chosen.dst, 0) + 1
        container_frequency[moved_cid] = container_frequency.get(moved_cid, 0) + 1

        moved_containers.add(moved_cid)
        repeated_flag = 0
        if edge in seen_edges:
            repeated_edges += 1
            repeated_flag = 1
        else:
            seen_edges.add(edge)
        reverse_flag = 0
        if last_edge is not None and last_edge[0] == edge[1] and last_edge[1] == edge[0]:
            immediate_reversals += 1
            reverse_flag = 1
        last_edge = edge

        quality_delta = _candidate_effective_quality(chosen, cfg)
        if quality_delta < 0.0:
            plateau_count = 0
            improving_window.append(1)
        else:
            plateau_count += 1
            improving_window.append(0)
        if should_shake:
            plateau_count = 0

        reversals_window.append(reverse_flag)
        repeated_window.append(repeated_flag)

        if cfg.reactive_tabu_enabled and len(reversals_window) >= max(2, window_size // 2):
            reversal_rate = sum(reversals_window) / float(len(reversals_window))
            repeat_rate = sum(repeated_window) / float(len(repeated_window))
            improving_rate = sum(improving_window) / float(len(improving_window)) if improving_window else 0.0

            next_tabu_len = current_tabu_len
            adjust_step = max(1, cfg.tabu_len_adjust_step)
            if reversal_rate >= cfg.tabu_reverse_rate_threshold or repeat_rate >= cfg.tabu_repeat_rate_threshold:
                next_tabu_len = min(max(cfg.tabu_len_min, cfg.tabu_len_max), current_tabu_len + adjust_step)
            elif improving_rate <= cfg.tabu_stagnation_rate_threshold:
                next_tabu_len = max(min(cfg.tabu_len_min, cfg.tabu_len_max), current_tabu_len - adjust_step)

            if next_tabu_len != current_tabu_len:
                current_tabu_len = next_tabu_len
                if metrics is not None:
                    metrics.tabu_len_curve.append((it + 1, current_tabu_len))

        # update best
        cur_objective = _objective_cost(state, cfg)
        if cur_objective + 1e-12 < best_objective:
            best_objective = cur_objective
            best_state = state.clone()
            best_moves = list(moves)
            plateau_count = 0
            _push_elite_state(elites, best_state, best_moves, best_objective, cfg)
        elif quality_delta < 0.0:
            _push_elite_state(elites, state, moves, cur_objective, cfg)

        if metrics is not None and (it + 1) % sample_every == 0:
            metrics.best_cost_curve.append((it + 1, best_state.cluster_cost()))

    if last_iteration + 1 >= cfg.tabu_iters:
        stop_reason = "iters_exhausted"

    if metrics is not None:
        metrics.total_search_moves = len(moves)
        metrics.unique_containers_moved = len(moved_containers)
        metrics.immediate_reversals = immediate_reversals
        metrics.repeated_edges = repeated_edges
        metrics.stop_reason = stop_reason
        metrics.restart_count = restart_count
        metrics.relink_steps_applied = relink_steps_applied
        final_x = last_iteration + 1 if last_iteration >= 0 else 0
        if not metrics.best_cost_curve or metrics.best_cost_curve[-1][0] != final_x:
            metrics.best_cost_curve.append((final_x, best_state.cluster_cost()))
        if not metrics.tabu_len_curve or metrics.tabu_len_curve[-1][0] != final_x:
            metrics.tabu_len_curve.append((final_x, current_tabu_len))

    reduced_moves = _compress_redundant_sequences(best_moves)
    if len(reduced_moves) < len(best_moves):
        replayed = _replay_moves(search_start, reduced_moves)
        if replayed is not None:
            replay_moves, replay_state = replayed
            if abs(_objective_cost(replay_state, cfg) - best_objective) <= 1e-9:
                best_moves = replay_moves
                best_state = replay_state

    return best_moves, best_state
