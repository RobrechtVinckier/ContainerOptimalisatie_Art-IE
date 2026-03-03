"""Crane timing and weighted travel helper functions."""

from __future__ import annotations

from ..core.constants import (
    CONTAINER_METERS,
    LENGTH_COST_WEIGHT,
    LENGTH_SPEED_MPS,
    VERTICAL_EMPTY_SPEED_MPS,
    VERTICAL_LOADED_SPEED_MPS,
    WIDTH_SPEED_MPS,
    YARD_HEIGHT,
)


def weighted_xy_cost(src_x: int | float, src_z: int | float, dst_x: int | float, dst_z: int | float) -> float:
    """Weighted horizontal crane movement cost (length axis weighted heavier)."""
    return float(abs(src_x - dst_x) + LENGTH_COST_WEIGHT * abs(src_z - dst_z))


def horizontal_travel_seconds(src_x: int | float, src_z: int | float, dst_x: int | float, dst_z: int | float) -> float:
    """Horizontal travel time between two stack coordinates in seconds."""
    dx_m = abs(src_x - dst_x) * CONTAINER_METERS["width"]
    dz_m = abs(src_z - dst_z) * CONTAINER_METERS["length"]
    return dx_m / WIDTH_SPEED_MPS + dz_m / LENGTH_SPEED_MPS


def stack_level_height_m(level: int) -> float:
    """Top height in meters for a given stack level index."""
    # Level 0 top sits at one container height above ground.
    return (level + 1) * CONTAINER_METERS["height"]


def travel_hook_height_m() -> float:
    """Return nominal empty travel hook height in meters."""
    return (YARD_HEIGHT + 1) * CONTAINER_METERS["height"]


def crane_move_seconds(
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
    """Estimate crane cycle duration for one pick-and-place move."""
    travel_height = travel_hook_height_m()
    pick_height = stack_level_height_m(src_level)
    place_height = stack_level_height_m(dst_level)

    horizontal_to_source = horizontal_travel_seconds(crane_x, crane_z, src_x, src_z)
    lower_empty = max(0.0, travel_height - pick_height) / VERTICAL_EMPTY_SPEED_MPS
    lift_loaded = max(0.0, travel_height - pick_height) / VERTICAL_LOADED_SPEED_MPS
    horizontal_with_load = horizontal_travel_seconds(src_x, src_z, dst_x, dst_z)
    lower_loaded = max(0.0, travel_height - place_height) / VERTICAL_LOADED_SPEED_MPS
    raise_empty = max(0.0, travel_height - place_height) / VERTICAL_EMPTY_SPEED_MPS

    return (
        horizontal_to_source
        + lower_empty
        + lift_loaded
        + horizontal_with_load
        + lower_loaded
        + raise_empty
    )
