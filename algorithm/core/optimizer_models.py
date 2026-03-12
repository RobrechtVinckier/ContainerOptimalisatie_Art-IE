"""Datamodels and configuration for optimizer search."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Tuple

try:
    from ..state import XY
except ImportError:  # pragma: no cover - CLI fallback
    from state import XY

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
    delta_quality: float = 0.0
    delta_stack_top_mismatch: float = 0.0
    delta_stack_transitions: float = 0.0
    delta_stack_rehandles: float = 0.0
    delta_stack_impurity: float = 0.0
    delta_buried_foreign: float = 0.0
    delta_group_fragmentation: float = 0.0
    operational_cost: float = 0.0
    frequency_penalty: float = 0.0


@dataclass
class OptimizerConfig:
    # reproducibility
    seed: int = 0

    night_budget_s: float = 28800.0
    lam: float = 0.1
    # stack-flow objective terms
    stack_top_mismatch_weight: float = 1.8
    stack_transition_weight: float = 1.6
    stack_rehandle_weight: float = 1.4
    stack_impurity_weight: float = 0.6
    buried_foreign_weight: float = 2.6
    group_fragmentation_weight: float = 0.1
    # secondary operational comparator for near-equal quality
    quality_tie_eps: float = 1e-9
    operational_weight: float = 1.25
    # scale operational score before combining with quality in primary ranking
    operational_normalizer: float = 28.0
    energy_weight: float = 1.8
    energy_x_cost: float = 14.0
    energy_y_cost: float = 1.0
    energy_z_cost: float = 1.1
    expensive_axis_deadhead_weight: float = 0.25
    expensive_axis_reversal_weight: float = 0.6

    # candidate generation controls
    top_groups: int = 5
    src_limit: int = 40
    dst_limit_per_src: int = 30
    x_radius: int = 2
    y_radius: int = 1
    y_aware: bool = True
    # soft move caps on the dominant expensive axis (<=0 disables)
    max_expensive_axis_src_delta: int = 4
    max_expensive_axis_move_delta: int = 3
    diversify_period: int = 0
    diversify_random_dsts: int = 0

    # tabu search controls
    tabu_len: int = 200
    tabu_iters: int = 1500
    tabu_mode: TabuMode = "combined"
    non_improving_penalty: float = 1.0
    top_k: int = 30
    selection_mode: SelectionMode = "topk_best_nontabu"
    plateau_iters: int = 120
    shake_enabled: bool = True
    # reactive tabu tenure controls
    reactive_tabu_enabled: bool = False
    tabu_len_min: int = 200
    tabu_len_max: int = 200
    tabu_reactive_window: int = 80
    tabu_reverse_rate_threshold: float = 0.12
    tabu_repeat_rate_threshold: float = 0.35
    tabu_stagnation_rate_threshold: float = 0.04
    tabu_len_adjust_step: int = 10
    # frequency memory weights
    frequency_edge_weight: float = 0.0
    frequency_stack_weight: float = 0.0
    frequency_container_weight: float = 0.0
    # diversification controls
    elite_pool_size: int = 4
    elite_restart_enabled: bool = False
    path_relink_enabled: bool = False
    path_relink_steps: int = 6

    # metrics
    metrics_sample_every: int = 50


@dataclass
class TabuMetrics:
    total_search_moves: int = 0
    unique_containers_moved: int = 0
    immediate_reversals: int = 0
    repeated_edges: int = 0
    best_cost_curve: List[Tuple[int, float]] = field(default_factory=list)
    tabu_len_curve: List[Tuple[int, int]] = field(default_factory=list)
    stop_reason: str = ""
    restart_count: int = 0
    relink_steps_applied: int = 0


@dataclass(frozen=True)
class _RankedCandidate:
    candidate: Candidate
    quality_score: float
    operational_score: float
    is_tabu: bool
