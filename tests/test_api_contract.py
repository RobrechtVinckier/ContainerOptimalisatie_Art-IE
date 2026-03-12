from __future__ import annotations

import asyncio
import unittest

from backend.app import database, main, schemas


class TestApiContract(unittest.TestCase):
    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def setUp(self) -> None:
        self.original_settings = database.get_algorithm_settings().model_copy(deep=True)

    def tearDown(self) -> None:
        restore_patch = schemas.AlgorithmSettingsPatch(**self.original_settings.model_dump())
        database.update_algorithm_settings(restore_patch)

    def test_get_config_contract(self) -> None:
        payload = self._run(main.get_config())
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
        self.assertEqual(payload["width"], database.YARD_WIDTH)
        self.assertEqual(payload["length"], database.YARD_LENGTH)
        self.assertEqual(payload["height"], database.YARD_HEIGHT)
        self.assertEqual(payload["lengthCostWeight"], database.LENGTH_COST_WEIGHT)

    def test_settings_patch_roundtrip(self) -> None:
        patch = schemas.AlgorithmSettingsPatch(
            seed=77,
            lam=1.8,
            nightBudget=24000.0,
            tabuIters=120,
            tabuLen=40,
            selectionMode="best",
        )
        patched = self._run(main.patch_algorithm_settings(patch))
        self.assertEqual(patched.seed, patch.seed)
        self.assertEqual(patched.lam, patch.lam)
        self.assertEqual(patched.nightBudget, patch.nightBudget)
        self.assertEqual(patched.tabuIters, patch.tabuIters)
        self.assertEqual(patched.tabuLen, patch.tabuLen)
        self.assertEqual(patched.selectionMode, patch.selectionMode)

        current = self._run(main.get_algorithm_settings())
        self.assertEqual(current.model_dump(), patched.model_dump())

    def test_random_and_solve_endpoint_contract(self) -> None:
        random_payload = self._run(
            main.create_random_simulation(
                schemas.RandomSimulationRequest(seed=2024, containerCount=24)
            )
        )
        self.assertEqual(random_payload["seed"], 2024)
        self.assertEqual(random_payload["summary"]["total"], 24)
        self.assertEqual(len(random_payload["stacks"]), database.YARD_WIDTH)
        self.assertEqual(len(random_payload["stacks"][0]), database.YARD_LENGTH)

        solve_payload = self._run(
            main.solve_simulation(
                schemas.SolveSimulationRequest(
                    stacks=random_payload["stacks"],
                    settings=schemas.AlgorithmSettingsPatch(seed=2024, tabuIters=80),
                )
            )
        )

        self.assertIn("moves", solve_payload)
        self.assertIn("nightStats", solve_payload)
        self.assertIn("dayCycle", solve_payload)
        self.assertIn("finalSummary", solve_payload)
        self.assertIn("finalStacks", solve_payload)
        self.assertEqual(len(solve_payload["finalStacks"]), database.YARD_WIDTH)
        self.assertEqual(len(solve_payload["finalStacks"][0]), database.YARD_LENGTH)

        if solve_payload["moves"]:
            move = solve_payload["moves"][0]
            self.assertEqual(
                set(move.keys()),
                {"id", "color", "from", "to", "weightedCost", "tStart", "tEnd", "durationSeconds"},
            )
            self.assertEqual(set(move["from"].keys()), {"x", "z", "y"})
            self.assertEqual(set(move["to"].keys()), {"x", "z", "y"})

        stats = solve_payload["dayCycle"]["stats"]
        self.assertGreaterEqual(stats["totalJobs"], 0)
        self.assertLessEqual(stats["totalJobs"], random_payload["summary"]["total"])

    def test_day_cycle_jobs_are_group_batched(self) -> None:
        random_payload = self._run(
            main.create_random_simulation(
                schemas.RandomSimulationRequest(seed=2024, containerCount=24)
            )
        )
        solve_payload = self._run(
            main.solve_simulation(
                schemas.SolveSimulationRequest(
                    stacks=random_payload["stacks"],
                    settings=schemas.AlgorithmSettingsPatch(seed=2024, tabuIters=80),
                )
            )
        )

        jobs = solve_payload["dayCycle"]["jobs"]
        windows = []
        last_color = None
        for job in jobs:
            color_name = job["containerColor"]
            if color_name != last_color:
                windows.append(color_name)
                last_color = color_name

        window_counts = {}
        for color_name in windows:
            window_counts[color_name] = window_counts.get(color_name, 0) + 1

        for color_name, count in window_counts.items():
            self.assertLessEqual(
                count,
                3,
                f"Color {color_name!r} was fragmented into too many day windows: {windows!r}",
            )
        self.assertLessEqual(
            len(windows),
            len(window_counts) + 5,
            f"Day plan switched companies too often: {windows!r}",
        )
        run_lengths = []
        current_length = 0
        current_color = None
        for job in jobs:
            color_name = job["containerColor"]
            if color_name != current_color:
                if current_length > 0:
                    run_lengths.append(current_length)
                current_color = color_name
                current_length = 1
            else:
                current_length += 1
        if current_length > 0:
            run_lengths.append(current_length)
        singleton_runs = sum(1 for length in run_lengths if length == 1)
        self.assertLessEqual(singleton_runs, 1, f"Too many singleton company chunks: {run_lengths!r}")

    def test_random_endpoint_accepts_random_setup_parameters(self) -> None:
        payload = self._run(
            main.create_random_simulation(
                schemas.RandomSimulationRequest(
                    groups=2,
                    containerCount=13,
                    minContainersPerGroup=5,
                    maxContainersPerGroup=8,
                )
            )
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

    def test_random_endpoint_accepts_groups_above_color_count(self) -> None:
        payload = self._run(
            main.create_random_simulation(
                schemas.RandomSimulationRequest(
                    groups=6,
                    containerCount=130,
                    minContainersPerGroup=5,
                    maxContainersPerGroup=60,
                )
            )
        )
        self.assertEqual(payload["summary"]["total"], 130)
        color_count = payload["summary"]["colorCount"]
        self.assertEqual(sum(color_count.values()), 130)
        non_zero_colors = [color for color, count in color_count.items() if count > 0]
        self.assertEqual(len(non_zero_colors), 6)
        for color in non_zero_colors:
            self.assertGreaterEqual(color_count[color], 5)
            self.assertLessEqual(color_count[color], 60)


if __name__ == "__main__":
    unittest.main()
