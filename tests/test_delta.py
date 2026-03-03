import random
import unittest
from typing import List, Tuple

from state import State


class TestConstraintsAndDelta(unittest.TestCase):
    def make_small_state(self, seed: int = 0) -> State:
        rng = random.Random(seed)
        X, Y, H = 4, 3, 3
        groups = 3
        per_group = 6
        n = groups * per_group
        group: List[int] = []
        for g in range(groups):
            group.extend([g] * per_group)

        ids = list(range(n))
        rng.shuffle(ids)

        yard = [[[] for _ in range(Y)] for _ in range(X)]
        coords = [(x, y) for x in range(X) for y in range(Y)]
        for cid in ids:
            while True:
                x, y = rng.choice(coords)
                if len(yard[x][y]) < H:
                    yard[x][y].append(cid)
                    break

        st = State.build_from_yard(X, Y, H, yard, group)
        st.crane_pos = (0, 0)
        st.time_used = 0.0
        return st

    def test_top_of_stack_constraint(self) -> None:
        st = self.make_small_state(1)
        # Find a stack with at least 2 containers
        src = None
        for x in range(st.X):
            for y in range(st.Y):
                if len(st.stack((x, y))) >= 2:
                    src = (x, y)
                    break
            if src:
                break
        self.assertIsNotNone(src)

        stack = st.stack(src)  # bottom->top
        non_top_cid = stack[0]

        # Attempt to "move" non-top by faking: apply_move should always move top, so we assert that.
        dst = None
        for x in range(st.X):
            for y in range(st.Y):
                if (x, y) != src and len(st.stack((x, y))) < st.H:
                    dst = (x, y)
                    break
            if dst:
                break
        self.assertIsNotNone(dst)

        moved = st.apply_move(src, dst)  # should move the top
        self.assertNotEqual(moved, non_top_cid, "apply_move must move top-of-stack only")
        # non_top should remain in src stack
        self.assertIn(non_top_cid, st.stack(src))

    def test_capacity_constraint(self) -> None:
        st = self.make_small_state(2)
        # Find a full destination stack
        dst = None
        for x in range(st.X):
            for y in range(st.Y):
                if len(st.stack((x, y))) == st.H:
                    dst = (x, y)
                    break
            if dst:
                break
        self.assertIsNotNone(dst)

        # Find a non-empty source different from dst
        src = None
        for x in range(st.X):
            for y in range(st.Y):
                if (x, y) != dst and len(st.stack((x, y))) > 0:
                    src = (x, y)
                    break
            if src:
                break
        self.assertIsNotNone(src)

        # can_move should be false and apply_move should raise
        self.assertFalse(st.can_move(src, dst))
        with self.assertRaises(ValueError):
            st.apply_move(src, dst)

    def test_delta_cluster_correctness_vs_bruteforce(self) -> None:
        st = self.make_small_state(3)
        rng = random.Random(3)

        for _ in range(200):
            # random legal move: choose random src with non-empty, random dst with capacity
            srcs = [(x, y) for x in range(st.X) for y in range(st.Y) if len(st.stack((x, y))) > 0]
            dsts = [(x, y) for x in range(st.X) for y in range(st.Y) if len(st.stack((x, y))) < st.H]

            src = rng.choice(srcs)
            dst = rng.choice(dsts)
            if src == dst or not st.can_move(src, dst):
                continue

            cid = st.top(src)
            self.assertIsNotNone(cid)

            before = st.compute_cluster_cost_bruteforce()
            delta_fast = st.delta_cluster_cost_for_move(cid, src, dst)

            # apply on a clone and recompute
            st2 = st.clone()
            st2.apply_move(src, dst)
            after = st2.compute_cluster_cost_bruteforce()
            delta_brute = after - before

            self.assertAlmostEqual(delta_fast, delta_brute, places=9)

    def assert_state_invariants(self, st: State) -> None:
        n = len(st.group)
        seen: set[int] = set()
        for x in range(st.X):
            for y in range(st.Y):
                self.assertLessEqual(len(st.stack((x, y))), st.H)
                for cid in st.stack((x, y)):
                    self.assertGreaterEqual(cid, 0)
                    self.assertLess(cid, n)
                    self.assertNotIn(cid, seen)
                    seen.add(cid)
        self.assertEqual(len(seen), n)

        recompute_count_x = [[0 for _ in range(st.X)] for _ in range(st.num_groups())]
        recompute_count_y = [[0 for _ in range(st.Y)] for _ in range(st.num_groups())]
        for cid in range(n):
            x, y = st.pos[cid]
            self.assertIn(cid, st.stack((x, y)))
            g = st.group[cid]
            recompute_count_x[g][x] += 1
            recompute_count_y[g][y] += 1

        self.assertEqual(st.count_x, recompute_count_x)
        self.assertEqual(st.count_y, recompute_count_y)

        for g in range(st.num_groups()):
            rx_min, rx_max = st._recompute_bounds_1d_from_counts(st.count_x[g])
            ry_min, ry_max = st._recompute_bounds_1d_from_counts(st.count_y[g])
            self.assertEqual((st.xmin[g], st.xmax[g]), (rx_min, rx_max))
            self.assertEqual((st.ymin[g], st.ymax[g]), (ry_min, ry_max))
            expected_spread = st._spread_from_bounds(rx_min, rx_max, ry_min, ry_max)
            self.assertAlmostEqual(st.spread[g], expected_spread, places=9)

        self.assertAlmostEqual(st.cluster_cost(), st.compute_cluster_cost_bruteforce(), places=9)

        # group->occupied-stack consistency for fragmentation objective
        occupancy = [0 for _ in range(st.num_groups())]
        for x in range(st.X):
            for y in range(st.Y):
                present = set(st.group[cid] for cid in st.stack((x, y)))
                for g in present:
                    occupancy[g] += 1
        st._ensure_group_stack_occupancy()
        self.assertEqual(st.group_stack_occupancy, occupancy)

    def test_randomized_sequences_preserve_invariants(self) -> None:
        seeds = [11, 12, 13, 14]
        for seed in seeds:
            st = self.make_small_state(seed)
            rng = random.Random(seed + 100)
            self.assert_state_invariants(st)
            for _ in range(160):
                legal = []
                for sx in range(st.X):
                    for sy in range(st.Y):
                        if st.top((sx, sy)) is None:
                            continue
                        for dx in range(st.X):
                            for dy in range(st.Y):
                                if st.can_move((sx, sy), (dx, dy)):
                                    legal.append(((sx, sy), (dx, dy)))
                self.assertGreater(len(legal), 0)
                src, dst = rng.choice(legal)
                cid = st.top(src)
                self.assertIsNotNone(cid)
                before = st.compute_cluster_cost_bruteforce()
                delta_fast = st.delta_cluster_cost_for_move(cid, src, dst)
                st_clone = st.clone()
                st_clone.apply_move(src, dst)
                after = st_clone.compute_cluster_cost_bruteforce()
                self.assertAlmostEqual(delta_fast, after - before, places=9)

                st.apply_move(src, dst)
                self.assert_state_invariants(st)

    def test_delta_stack_quality_and_fragmentation_correctness(self) -> None:
        st = self.make_small_state(21)
        rng = random.Random(2101)
        for _ in range(180):
            legal = []
            for sx in range(st.X):
                for sy in range(st.Y):
                    if st.top((sx, sy)) is None:
                        continue
                    for dx in range(st.X):
                        for dy in range(st.Y):
                            if st.can_move((sx, sy), (dx, dy)):
                                legal.append(((sx, sy), (dx, dy)))
            self.assertGreater(len(legal), 0)
            src, dst = rng.choice(legal)
            cid = st.top(src)
            self.assertIsNotNone(cid)

            before_stack = st.total_stack_quality_cost(
                top_mismatch_weight=0.7,
                rehandle_weight=1.1,
                impurity_weight=1.5,
                buried_foreign_weight=2.0,
            )
            before_frag = st.total_group_fragmentation_cost()
            delta_stack = st.delta_stack_quality_for_move(
                cid,
                src,
                dst,
                top_mismatch_weight=0.7,
                rehandle_weight=1.1,
                impurity_weight=1.5,
                buried_foreign_weight=2.0,
            )
            delta_frag = st.delta_group_fragmentation_for_move(cid, src, dst)

            st2 = st.clone()
            st2.apply_move(src, dst)
            after_stack = st2.total_stack_quality_cost(
                top_mismatch_weight=0.7,
                rehandle_weight=1.1,
                impurity_weight=1.5,
                buried_foreign_weight=2.0,
            )
            after_frag = st2.total_group_fragmentation_cost()

            self.assertAlmostEqual(delta_stack, after_stack - before_stack, places=9)
            self.assertAlmostEqual(delta_frag, after_frag - before_frag, places=9)
            st = st2


if __name__ == "__main__":
    unittest.main()
