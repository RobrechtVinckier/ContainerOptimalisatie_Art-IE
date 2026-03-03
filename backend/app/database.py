from __future__ import annotations

from typing import Dict, List, Mapping, Tuple

from . import schemas
from .core.constants import (
    COLOR_ORDER,
    COLOR_TO_GROUP,
    COMPANY_BY_COLOR,
    CONTAINER_METERS,
    DAY_COMPANY_SWITCH_PENALTY,
    DAY_DURATION_SECONDS,
    DAY_END_SECONDS,
    DAY_ENERGY_WEIGHT,
    DAY_INCOMPLETE_COMPANY_SWITCH_PENALTY,
    DAY_START_SECONDS,
    DAY_TRUCK_SLOTS,
    DEFAULT_CONTAINER_COUNT,
    LENGTH_COST_WEIGHT,
    LENGTH_SPEED_MPS,
    NIGHT_COMPANY_TARGET_Z,
    TARGET_PATTERNS,
    TRUCK_FLOW_HEADWAY_SECONDS,
    TRUCK_LANE_WIDTH,
    TRUCK_LOAD_BUFFER_SECONDS,
    TRUCK_PICKUP_X,
    VERTICAL_EMPTY_SPEED_MPS,
    VERTICAL_LOADED_SPEED_MPS,
    WIDTH_SPEED_MPS,
    YARD_HEIGHT,
    YARD_LENGTH,
    YARD_WIDTH,
)
from .services import day_cycle_service, night_stage_service, optimizer_service, solve_service, stack_service, timing_service

# Backward-compatible mutable settings state.
ALGORITHM_SETTINGS = schemas.AlgorithmSettings()


def yard_config_payload() -> dict:
    return stack_service.yard_config_payload()


def get_algorithm_settings() -> schemas.AlgorithmSettings:
    return ALGORITHM_SETTINGS


def update_algorithm_settings(patch: schemas.AlgorithmSettingsPatch) -> schemas.AlgorithmSettings:
    global ALGORITHM_SETTINGS

    current = ALGORITHM_SETTINGS.model_dump()
    updates = patch.model_dump(exclude_none=True)
    current.update(updates)
    ALGORITHM_SETTINGS = schemas.AlgorithmSettings(**current)
    return ALGORITHM_SETTINGS


def create_empty_stacks() -> List[List[List[dict]]]:
    return stack_service.create_empty_stacks()


def _normalize_container(container) -> dict:
    return stack_service._normalize_container(container)


def clone_stacks(stacks) -> List[List[List[dict]]]:
    return stack_service.clone_stacks(stacks)


def target_color_for_slot(x: int, z: int) -> str:
    return stack_service.target_color_for_slot(x, z)


def summarize_stacks(stacks: List[List[List[dict]]], *, score_weights: Mapping[str, float] | None = None) -> dict:
    return stack_service.summarize_stacks(stacks, score_weights=score_weights)


def is_solved(stacks: List[List[List[dict]]]) -> bool:
    return stack_service.is_solved(stacks)


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
) -> dict:
    score_weights = stack_service.placement_score_weights_from_algorithm_settings(get_algorithm_settings())
    return stack_service.random_configuration(
        seed=seed,
        container_count=container_count,
        yard_x=yard_x,
        yard_y=yard_y,
        yard_h=yard_h,
        groups=groups,
        containers_per_group=containers_per_group,
        min_containers_per_group=min_containers_per_group,
        max_containers_per_group=max_containers_per_group,
        score_weights=score_weights,
    )


def _state_from_stacks(stacks: List[List[List[dict]]]):
    return optimizer_service.state_from_stacks(stacks)


def _optimizer_config(settings: schemas.AlgorithmSettings):
    return optimizer_service.optimizer_config(settings)


def _convert_moves_to_frontend(
    moves,
    stacks: List[List[List[dict]]],
    night_budget_s: float | None = None,
):
    return optimizer_service.convert_moves_to_frontend(moves, stacks, night_budget_s=night_budget_s)


def _slot_to_stack_z(slot_index: int) -> int:
    return day_cycle_service.slot_to_stack_z(slot_index)


def _top_containers(stacks: List[List[List[dict]]]):
    return day_cycle_service.top_containers(stacks)


def _weighted_xy_cost(src_x: int | float, src_z: int | float, dst_x: int | float, dst_z: int | float) -> float:
    return timing_service.weighted_xy_cost(src_x, src_z, dst_x, dst_z)


def _horizontal_travel_seconds(src_x: int | float, src_z: int | float, dst_x: int | float, dst_z: int | float) -> float:
    return timing_service.horizontal_travel_seconds(src_x, src_z, dst_x, dst_z)


def _stack_level_height_m(level: int) -> float:
    return timing_service.stack_level_height_m(level)


def _travel_hook_height_m() -> float:
    return timing_service.travel_hook_height_m()


def _crane_move_seconds(
    *,
    crane_x: int | float,
    crane_z: int | float,
    src_x: int,
    src_z: int,
    src_level: int,
    dst_x: int | float,
    dst_z: int | float,
    dst_level: int,
) -> float:
    return timing_service.crane_move_seconds(
        crane_x=crane_x,
        crane_z=crane_z,
        src_x=src_x,
        src_z=src_z,
        src_level=src_level,
        dst_x=dst_x,
        dst_z=dst_z,
        dst_level=dst_level,
    )


def _estimate_truck_timing(
    *,
    load_start: float,
    load_end: float,
    slot_index: int,
    lane_flow_free_at: float,
) -> Tuple[float, float, float]:
    return day_cycle_service.estimate_truck_timing(
        load_start=load_start,
        load_end=load_end,
        slot_index=slot_index,
        lane_flow_free_at=lane_flow_free_at,
    )


def _build_day_cycle_plan(stacks: List[List[List[dict]]], day_seed: int) -> dict:
    return day_cycle_service.build_day_cycle_plan(stacks, day_seed=day_seed)


def _night_stage_for_day(
    stacks: List[List[List[dict]]],
    night_budget_s: float,
    day_seed: int,
    *,
    start_time_s: float = 0.0,
    crane_start: Tuple[float, float] = (2.0, 0.0),
):
    return night_stage_service.night_stage_for_day(
        stacks,
        night_budget_s,
        day_seed,
        start_time_s=start_time_s,
        crane_start=crane_start,
    )


def solve_stacks(stacks: List[List[List[dict]]], settings_patch: schemas.AlgorithmSettingsPatch | None = None) -> dict:
    settings = get_algorithm_settings()
    if settings_patch is not None:
        merged = settings.model_dump()
        merged.update(settings_patch.model_dump(exclude_none=True))
        settings = schemas.AlgorithmSettings(**merged)
    return solve_service.solve_stacks(stacks, settings)


def __getattr__(name: str):
    """Backwards-compatible attribute access for mutable settings state."""
    if name == "ALGORITHM_SETTINGS":
        return ALGORITHM_SETTINGS
    raise AttributeError(name)
