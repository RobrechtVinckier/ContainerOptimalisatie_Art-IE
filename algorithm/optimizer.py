from __future__ import annotations

try:
    from .core.candidate_generation import _mix_seed, _move_energy_cost, _stack_top_height, generate_candidate_moves
    from .core.optimizer_models import (
        Candidate,
        OptimizerConfig,
        SelectionMode,
        TabuMetrics,
        TabuMode,
        _RankedCandidate,
    )
    from .core.search import (
        _is_tabu,
        _rank_candidates,
        _register_tabu,
        _select_ranked_candidate,
        _tabu_score,
        greedy_plan,
        tabu_improve,
    )
except ImportError:  # pragma: no cover - CLI fallback
    from core.candidate_generation import _mix_seed, _move_energy_cost, _stack_top_height, generate_candidate_moves
    from core.optimizer_models import (
        Candidate,
        OptimizerConfig,
        SelectionMode,
        TabuMetrics,
        TabuMode,
        _RankedCandidate,
    )
    from core.search import (
        _is_tabu,
        _rank_candidates,
        _register_tabu,
        _select_ranked_candidate,
        _tabu_score,
        greedy_plan,
        tabu_improve,
    )

__all__ = [
    "TabuMode",
    "SelectionMode",
    "Candidate",
    "OptimizerConfig",
    "TabuMetrics",
    "_RankedCandidate",
    "_mix_seed",
    "_stack_top_height",
    "_move_energy_cost",
    "generate_candidate_moves",
    "greedy_plan",
    "_tabu_score",
    "_is_tabu",
    "_register_tabu",
    "_rank_candidates",
    "_select_ranked_candidate",
    "tabu_improve",
]
