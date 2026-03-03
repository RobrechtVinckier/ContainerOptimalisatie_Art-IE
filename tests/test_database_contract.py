from __future__ import annotations

import unittest
from typing import Any, Dict, List

from backend.app import database, schemas


def _stack_heights(stacks: List[List[List[dict]]]) -> List[List[int]]:
    return [[len(stacks[x][z]) for z in range(database.YARD_LENGTH)] for x in range(database.YARD_WIDTH)]


def _solve_signature(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "moves_len": len(payload["moves"]),
        "solved": payload["solved"],
        "totalWeightedCost": payload["totalWeightedCost"],
        "finalSummary": payload["finalSummary"],
        "nightStats": payload["nightStats"],
        "dayStats": payload["dayCycle"]["stats"],
        "final_heights": _stack_heights(payload["finalStacks"]),
    }


class TestDatabaseContract(unittest.TestCase):
    def setUp(self) -> None:
        self.original_settings = database.get_algorithm_settings().model_copy(deep=True)

    def tearDown(self) -> None:
        restore_patch = schemas.AlgorithmSettingsPatch(**self.original_settings.model_dump())
        database.update_algorithm_settings(restore_patch)

    def test_yard_config_payload_contract(self) -> None:
        payload = database.yard_config_payload()
        self.assertEqual(payload["width"], database.YARD_WIDTH)
        self.assertEqual(payload["length"], database.YARD_LENGTH)
        self.assertEqual(payload["height"], database.YARD_HEIGHT)
        self.assertEqual(payload["containerCount"], database.DEFAULT_CONTAINER_COUNT)
        self.assertEqual(payload["lengthCostWeight"], database.LENGTH_COST_WEIGHT)
        self.assertEqual(
            set(payload.keys()),
            {
                "width",
                "length",
                "height",
                "truckLaneWidth",
                "containerCount",
                "lengthCostWeight",
                "containerMeters",
            },
        )

    def test_random_configuration_capacity_guard(self) -> None:
        max_capacity = database.YARD_WIDTH * database.YARD_LENGTH * database.YARD_HEIGHT
        with self.assertRaises(ValueError):
            database.random_configuration(seed=1, container_count=max_capacity + 1)

    def test_random_configuration_supports_group_range_distribution(self) -> None:
        payload = database.random_configuration(
            seed=17,
            groups=2,
            container_count=13,
            min_containers_per_group=5,
            max_containers_per_group=8,
        )
        self.assertEqual(payload["summary"]["total"], 13)
        red = payload["summary"]["colorCount"]["red"]
        green = payload["summary"]["colorCount"]["green"]
        self.assertGreaterEqual(red, 5)
        self.assertLessEqual(red, 8)
        self.assertGreaterEqual(green, 5)
        self.assertLessEqual(green, 8)
        self.assertEqual(red + green, 13)
        self.assertEqual(payload["summary"]["colorCount"]["blue"], 0)

        for x in range(database.YARD_WIDTH):
            for z in range(database.YARD_LENGTH):
                stack = payload["stacks"][x][z]
                self.assertLessEqual(len(stack), database.YARD_HEIGHT)

    def test_random_configuration_assigns_unique_color_per_group(self) -> None:
        payload = database.random_configuration(
            seed=123,
            groups=3,
            container_count=40,
            min_containers_per_group=8,
            max_containers_per_group=20,
        )
        color_count = payload["summary"]["colorCount"]
        used_colors = [color for color, count in color_count.items() if count > 0]
        self.assertEqual(len(used_colors), 3)
        self.assertEqual(len(set(used_colors)), 3)
        self.assertEqual(sum(color_count.values()), 40)
        for color in used_colors:
            self.assertGreaterEqual(color_count[color], 8)
            self.assertLessEqual(color_count[color], 20)

    def test_random_configuration_accepts_groups_above_color_count(self) -> None:
        payload = database.random_configuration(
            seed=321,
            groups=6,
            container_count=130,
            min_containers_per_group=5,
            max_containers_per_group=60,
        )
        self.assertEqual(payload["summary"]["total"], 130)
        color_count = payload["summary"]["colorCount"]
        self.assertEqual(sum(color_count.values()), 130)
        non_zero_colors = [color for color, count in color_count.items() if count > 0]
        self.assertEqual(len(non_zero_colors), 6)
        for color in non_zero_colors:
            self.assertGreaterEqual(color_count[color], 5)
            self.assertLessEqual(color_count[color], 60)
        for x in range(database.YARD_WIDTH):
            for z in range(database.YARD_LENGTH):
                self.assertLessEqual(len(payload["stacks"][x][z]), database.YARD_HEIGHT)

    def test_solve_stacks_dimension_guard(self) -> None:
        invalid = [[[]]]
        with self.assertRaises(ValueError):
            database.solve_stacks(invalid)

    def test_solve_stacks_deterministic_for_same_input_and_seed(self) -> None:
        random_payload = database.random_configuration(seed=909, container_count=26)
        stacks = random_payload["stacks"]
        settings_patch = schemas.AlgorithmSettingsPatch(seed=909, tabuIters=120)

        solution_a = database.solve_stacks(stacks, settings_patch=settings_patch)
        solution_b = database.solve_stacks(stacks, settings_patch=settings_patch)
        self.assertEqual(_solve_signature(solution_a), _solve_signature(solution_b))

    def test_update_algorithm_settings_merges_partial_patch(self) -> None:
        before = database.get_algorithm_settings().model_dump()
        patched = database.update_algorithm_settings(schemas.AlgorithmSettingsPatch(topK=17))
        self.assertEqual(patched.topK, 17)
        self.assertEqual(patched.seed, before["seed"])
        self.assertEqual(patched.selectionMode, before["selectionMode"])


if __name__ == "__main__":
    unittest.main()
