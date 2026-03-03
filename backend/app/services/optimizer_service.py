"""Bridge services between backend stack payloads and optimization engine."""

from __future__ import annotations

from typing import Dict, List, Tuple

from algorithm.optimizer import OptimizerConfig
from algorithm.state import State

from .. import schemas
from ..core.constants import COLOR_TO_GROUP, LENGTH_COST_WEIGHT, YARD_HEIGHT, YARD_LENGTH, YARD_WIDTH
from .stack_service import clone_stacks
from .timing_service import crane_move_seconds


def state_from_stacks(stacks: List[List[List[dict]]]) -> Tuple[State, Dict[int, dict]]:
    """Build algorithm State from frontend stack payloads."""
    # Algorithm axis mapping:
    # algorithm X -> yard length (z), algorithm Y -> yard width (x)
    yard = [[[] for _ in range(YARD_WIDTH)] for _ in range(YARD_LENGTH)]
    group: List[int] = []
    metadata: Dict[int, dict] = {}
    color_to_group = dict(COLOR_TO_GROUP)
    next_group_id = max(color_to_group.values(), default=-1) + 1

    for x in range(YARD_WIDTH):
        for z in range(YARD_LENGTH):
            for container in stacks[x][z]:
                cid = len(group)
                color_name = container["color"]
                group_id = color_to_group.get(color_name)
                if group_id is None:
                    group_id = next_group_id
                    color_to_group[color_name] = group_id
                    next_group_id += 1
                group.append(group_id)
                yard[z][x].append(cid)
                metadata[cid] = {"id": container["id"], "color": color_name}

    state = State.build_from_yard(X=YARD_LENGTH, Y=YARD_WIDTH, H=YARD_HEIGHT, yard=yard, group=group)
    state.crane_pos = (0, 0)
    state.time_used = 0.0
    return state, metadata


def optimizer_config(settings: schemas.AlgorithmSettings) -> OptimizerConfig:
    """Map API settings model to optimizer configuration."""
    return OptimizerConfig(
        seed=settings.seed,
        lam=settings.lam,
        stack_top_mismatch_weight=settings.stackTopMismatchWeight,
        stack_rehandle_weight=settings.stackRehandleWeight,
        stack_impurity_weight=settings.stackImpurityWeight,
        buried_foreign_weight=settings.buriedForeignWeight,
        group_fragmentation_weight=settings.groupFragmentationWeight,
        quality_tie_eps=settings.qualityTieEps,
        operational_weight=settings.operationalWeight,
        night_budget_s=settings.nightBudget,
        energy_weight=settings.energyWeight,
        energy_x_cost=settings.energyXCost,
        energy_y_cost=settings.energyYCost,
        energy_z_cost=settings.energyZCost,
        top_groups=settings.topGroups,
        src_limit=settings.srcLimit,
        dst_limit_per_src=settings.dstLimit,
        x_radius=settings.xRadius,
        y_radius=settings.yRadius,
        y_aware=settings.yAware,
        diversify_period=settings.diversifyPeriod,
        diversify_random_dsts=settings.diversifyRandomDsts,
        tabu_iters=settings.tabuIters,
        tabu_len=settings.tabuLen,
        tabu_mode=settings.tabuMode,
        selection_mode=settings.selectionMode,
        top_k=settings.topK,
        non_improving_penalty=settings.nonImprovingPenalty,
        plateau_iters=settings.plateauIters,
        shake_enabled=settings.shakeEnabled,
        reactive_tabu_enabled=settings.reactiveTabuEnabled,
        tabu_len_min=settings.tabuLenMin,
        tabu_len_max=settings.tabuLenMax,
        tabu_reactive_window=settings.tabuReactiveWindow,
        tabu_reverse_rate_threshold=settings.tabuReverseRateThreshold,
        tabu_repeat_rate_threshold=settings.tabuRepeatRateThreshold,
        tabu_stagnation_rate_threshold=settings.tabuStagnationRateThreshold,
        tabu_len_adjust_step=settings.tabuLenAdjustStep,
        frequency_edge_weight=settings.frequencyEdgeWeight,
        frequency_stack_weight=settings.frequencyStackWeight,
        frequency_container_weight=settings.frequencyContainerWeight,
        elite_pool_size=settings.elitePoolSize,
        elite_restart_enabled=settings.eliteRestartEnabled,
        path_relink_enabled=settings.pathRelinkEnabled,
        path_relink_steps=settings.pathRelinkSteps,
        metrics_sample_every=settings.metricsSampleEvery,
    )


def convert_moves_to_frontend(
    moves,
    stacks: List[List[List[dict]]],
    night_budget_s: float | None = None,
) -> Tuple[List[dict], List[List[List[dict]]]]:
    """Convert optimizer moves to frontend payload and mutate stacks accordingly."""
    working = clone_stacks(stacks)
    output: List[dict] = []
    crane_x = 2.0
    crane_z = 0.0
    timeline_s = 0.0

    for move in moves:
        src_x = move.src[1]
        src_z = move.src[0]
        dst_x = move.dst[1]
        dst_z = move.dst[0]

        source = working[src_x][src_z]
        destination = working[dst_x][dst_z]
        if not source or len(destination) >= YARD_HEIGHT:
            continue

        from_y = len(source) - 1
        to_y = len(destination)
        duration_seconds = crane_move_seconds(
            crane_x=crane_x,
            crane_z=crane_z,
            src_x=src_x,
            src_z=src_z,
            src_level=from_y,
            dst_x=dst_x,
            dst_z=dst_z,
            dst_level=to_y,
        )
        t_start = timeline_s
        t_end = t_start + duration_seconds
        if night_budget_s is not None and t_end > night_budget_s:
            break

        container = source.pop()
        timeline_s = t_end
        crane_x = float(dst_x)
        crane_z = float(dst_z)
        destination.append(container)

        weighted_cost = abs(src_x - dst_x) + LENGTH_COST_WEIGHT * abs(src_z - dst_z)
        output.append(
            {
                "id": container["id"],
                "color": container["color"],
                "from": {"x": src_x, "z": src_z, "y": from_y},
                "to": {"x": dst_x, "z": dst_z, "y": to_y},
                "weightedCost": weighted_cost,
                "tStart": t_start,
                "tEnd": t_end,
                "durationSeconds": duration_seconds,
            }
        )

    return output, working
