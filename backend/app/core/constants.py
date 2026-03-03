"""Core constants shared across backend services."""

from __future__ import annotations

YARD_WIDTH = 5
YARD_LENGTH = 10
YARD_HEIGHT = 4
TRUCK_LANE_WIDTH = 2
DEFAULT_CONTAINER_COUNT = 130
LENGTH_COST_WEIGHT = 10
DAY_TRUCK_SLOTS = 10
TRUCK_PICKUP_X = YARD_WIDTH
TRUCK_FLOW_HEADWAY_SECONDS = 6.0
TRUCK_LOAD_BUFFER_SECONDS = 20.0
DAY_START_SECONDS = 6 * 3600
DAY_END_SECONDS = 22 * 3600
DAY_DURATION_SECONDS = DAY_END_SECONDS - DAY_START_SECONDS

# Crane timing model (meters and m/s)
LENGTH_SPEED_MPS = 1.0
WIDTH_SPEED_MPS = 2.0
VERTICAL_EMPTY_SPEED_MPS = 1.2
VERTICAL_LOADED_SPEED_MPS = 0.7
DAY_ENERGY_WEIGHT = 6.0
DAY_COMPANY_SWITCH_PENALTY = 140.0
DAY_INCOMPLETE_COMPANY_SWITCH_PENALTY = 720.0

NIGHT_COMPANY_TARGET_Z = {
    "red": 1,
    "green": 5,
    "blue": 8,
}

CONTAINER_METERS = {
    "length": 12.19,
    "width": 2.44,
    "height": 2.59,
}

COLOR_ORDER = ("red", "green", "blue")
COLOR_TO_GROUP = {"red": 0, "green": 1, "blue": 2}
TARGET_PATTERNS = (
    ("red", "green", "blue", "red", "green"),
    ("green", "blue", "red", "green", "blue"),
    ("blue", "red", "green", "blue", "red"),
)
COMPANY_BY_COLOR = {
    "red": {"company": "Aster Freight", "truckColor": "#cc4347"},
    "green": {"company": "Boreal Cargo", "truckColor": "#2d9c60"},
    "blue": {"company": "Cobalt Haul", "truckColor": "#3e64c7"},
}
