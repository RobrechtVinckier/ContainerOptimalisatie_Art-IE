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


if __name__ == "__main__":
    unittest.main()