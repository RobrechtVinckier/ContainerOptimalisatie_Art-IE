"""Solve orchestration for backend stack payloads."""

from __future__ import annotations

from typing import List

from algorithm.optimizer import TabuMetrics, greedy_plan, tabu_improve

from .. import schemas
from ..core.constants import LENGTH_COST_WEIGHT, YARD_LENGTH, YARD_WIDTH
from .day_cycle_service import build_day_cycle_plan
from .night_stage_service import night_stage_for_day
from .optimizer_service import convert_moves_to_frontend, optimizer_config, state_from_stacks
from .stack_service import (
    clone_stacks,
    is_solved,
    placement_score_weights_from_algorithm_settings,
    summarize_stacks,
)


def solve_stacks(stacks: List[List[List[dict]]], settings: schemas.AlgorithmSettings) -> dict:
    """Run greedy+tabu night optimization and build day-cycle plan."""
    if len(stacks) != YARD_WIDTH or any(len(column) != YARD_LENGTH for column in stacks):
        raise ValueError("Invalid stack dimensions")

    initial = clone_stacks(stacks)
    state, _metadata = state_from_stacks(initial)
    cfg = optimizer_config(settings)
    score_weights = placement_score_weights_from_algorithm_settings(settings)

    greedy_state = state.clone()
    greedy_moves = greedy_plan(greedy_state, cfg)

    tabu_state = greedy_state.clone()
    tabu_metrics = TabuMetrics()
    tabu_moves, _best_state = tabu_improve(tabu_state, cfg, metrics=tabu_metrics)

    full_moves = list(greedy_moves) + list(tabu_moves)
    frontend_moves, final_stacks = convert_moves_to_frontend(
        full_moves,
        initial,
        night_budget_s=float(settings.nightBudget),
    )
    algorithm_night_time = float(frontend_moves[-1]["tEnd"]) if frontend_moves else 0.0
    crane_start = (float(frontend_moves[-1]["to"]["x"]), float(frontend_moves[-1]["to"]["z"])) if frontend_moves else (
        2.0,
        0.0,
    )

    day_prep_moves, staged_stacks, staged_end_time = night_stage_for_day(
        final_stacks,
        night_budget_s=float(settings.nightBudget),
        day_seed=settings.seed,
        start_time_s=algorithm_night_time,
        crane_start=crane_start,
    )
    if day_prep_moves:
        frontend_moves.extend(day_prep_moves)
        final_stacks = staged_stacks
    total_night_time = max(algorithm_night_time, staged_end_time)

    total_weighted_cost = sum(move["weightedCost"] for move in frontend_moves)
    initial_summary = summarize_stacks(initial, score_weights=score_weights)
    final_summary = summarize_stacks(final_stacks, score_weights=score_weights)

    night_stats = {
        "greedyMoveCount": len(greedy_moves),
        "tabuMoveCount": len(tabu_moves),
        "tabuSearchMoveCount": tabu_metrics.total_search_moves,
        "tabuUniqueContainersMoved": tabu_metrics.unique_containers_moved,
        "tabuImmediateReversals": tabu_metrics.immediate_reversals,
        "tabuRepeatedEdges": tabu_metrics.repeated_edges,
        "tabuStopReason": tabu_metrics.stop_reason,
        "tabuRestarts": tabu_metrics.restart_count,
        "tabuRelinkSteps": tabu_metrics.relink_steps_applied,
        "dayPrepMoveCount": len(day_prep_moves),
        "totalMoves": len(frontend_moves),
        "timeUsedSeconds": total_night_time,
        "budgetSeconds": float(settings.nightBudget),
        "startPlacementScore": initial_summary["placementScore"],
        "endPlacementScore": final_summary["placementScore"],
        "lengthCostWeight": LENGTH_COST_WEIGHT,
    }
    day_cycle = build_day_cycle_plan(final_stacks, day_seed=settings.seed)

    return {
        "moves": frontend_moves,
        "solved": is_solved(final_stacks),
        "totalWeightedCost": total_weighted_cost,
        "finalSummary": final_summary,
        "finalStacks": final_stacks,
        "nightStats": night_stats,
        "dayCycle": day_cycle,
    }
