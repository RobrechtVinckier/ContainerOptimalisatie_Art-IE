import random
import unittest
from typing import List, Tuple

from optimizer import OptimizerConfig, TabuMetrics, generate_candidate_moves, tabu_improve
from state import State


class TestTabuBehavior(unittest.TestCase):
    def make_random_state(
        self,
        seed: int = 0,
        X: int = 6,
        Y: int = 4,
        H: int = 3,
        groups: int = 4,
        per_group: int = 8,
    ) -> State:
        rng = random.Random(seed)
        n = groups * per_group
        self.assertLessEqual(n, X * Y * H)

        group: List[int] = []
        for g in range(groups):
            group.extend([g] * per_group)

        ids = list(range(n))
        rng.shuffle(ids)

        yard: List[List[List[int]]] = [[[] for _ in range(Y)] for _ in range(X)]
        coords = [(x, y) for x in range(X) for y in range(Y)]
        for cid in ids:
            while True:
                x, y = rng.choice(coords)
                if len(yard[x][y]) < H:
                    yard[x][y].append(cid)
                    break

        st = State.build_from_yard(X=X, Y=Y, H=H, yard=yard, group=group)
        st.crane_pos = (0, 0)
        st.time_used = 0.0
        return st

    def make_ping_pong_state(self) -> State:
        # Two-stack setup where a single improving move can be immediately undone.
        X, Y, H = 2, 1, 2
        yard: List[List[List[int]]] = [[[] for _ in range(Y)] for _ in range(X)]
        yard[0][0] = [0]
        yard[1][0] = [1]
        group = [0, 0]

        st = State.build_from_yard(X=X, Y=Y, H=H, yard=yard, group=group)
        st.crane_pos = (0, 0)
        st.time_used = 0.0
        return st

    def move_signature(self, moves: List) -> List[Tuple[int, Tuple[int, int], Tuple[int, int]]]:
        return [(m.container_id, m.src, m.dst) for m in moves]

    def test_edge_reverse_tabu_blocks_immediate_reversal(self) -> None:
        base_state = self.make_ping_pong_state()
        base_cfg = OptimizerConfig(
            seed=11,
            night_budget_s=1000.0,
            lam=1.0,
            top_groups=1,
            src_limit=2,
            dst_limit_per_src=2,
            x_radius=2,
            y_radius=0,
            y_aware=True,
            tabu_iters=8,
            tabu_len=4,
            selection_mode="best",
            non_improving_penalty=0.0,
            plateau_iters=999,
            shake_enabled=False,
        )

        metrics_without_reverse = TabuMetrics()
        tabu_improve(base_state.clone(), base_cfg, metrics=metrics_without_reverse)
        self.assertGreater(
            metrics_without_reverse.immediate_reversals,
            0,
            "Baseline mode should show immediate backtracking in this scenario.",
        )

        cfg_reverse = OptimizerConfig(**{**base_cfg.__dict__, "tabu_mode": "edge_reverse"})
        metrics_with_reverse = TabuMetrics()
        tabu_improve(base_state.clone(), cfg_reverse, metrics=metrics_with_reverse)
        self.assertEqual(metrics_with_reverse.immediate_reversals, 0)

    def test_tabu_run_is_deterministic_for_fixed_seed(self) -> None:
        state_a = self.make_random_state(seed=23)
        state_b = state_a.clone()

        cfg = OptimizerConfig(
            seed=23,
            night_budget_s=3000.0,
            lam=1.0,
            top_groups=4,
            src_limit=30,
            dst_limit_per_src=20,
            x_radius=2,
            y_radius=1,
            y_aware=True,
            diversify_period=3,
            diversify_random_dsts=2,
            tabu_iters=120,
            tabu_len=25,
            tabu_mode="combined",
            top_k=12,
            selection_mode="topk_deterministic",
            non_improving_penalty=1.0,
            plateau_iters=40,
            shake_enabled=True,
        )

        moves1, _ = tabu_improve(state_a, cfg)
        moves2, _ = tabu_improve(state_b, cfg)
        sig1 = self.move_signature(moves1)
        sig2 = self.move_signature(moves2)

        self.assertGreater(len(sig1), 0)
        self.assertEqual(sig1, sig2)

    def test_replaying_best_moves_respects_constraints(self) -> None:
        initial = self.make_random_state(seed=7)
        cfg = OptimizerConfig(
            seed=7,
            night_budget_s=3000.0,
            lam=1.0,
            top_groups=4,
            src_limit=30,
            dst_limit_per_src=20,
            x_radius=2,
            y_radius=1,
            y_aware=True,
            tabu_iters=120,
            tabu_len=30,
            tabu_mode="combined",
            top_k=10,
            selection_mode="topk_best_nontabu",
            non_improving_penalty=1.0,
            plateau_iters=40,
            shake_enabled=True,
        )

        moves, best_state = tabu_improve(initial.clone(), cfg)
        replay = initial.clone()

        for move in moves:
            self.assertTrue(replay.can_move(move.src, move.dst))
            top_before = replay.top(move.src)
            self.assertEqual(top_before, move.container_id)
            moved = replay.apply_move(move.src, move.dst)
            self.assertEqual(moved, move.container_id)

            for x in range(replay.X):
                for y in range(replay.Y):
                    self.assertLessEqual(len(replay.stack((x, y))), replay.H)

        self.assertAlmostEqual(replay.cluster_cost(), best_state.cluster_cost(), places=9)
        self.assertAlmostEqual(replay.time_used, best_state.time_used, places=9)

    def test_energy_cost_penalizes_width_more_than_depth(self) -> None:
        X, Y, H = 2, 5, 1
        yard: List[List[List[int]]] = [[[] for _ in range(Y)] for _ in range(X)]
        yard[0][0] = [0]
        st = State.build_from_yard(X=X, Y=Y, H=H, yard=yard, group=[0])
        st.crane_pos = (0, 0)
        st.time_used = 0.0

        cfg = OptimizerConfig(
            seed=1,
            lam=0.0,
            energy_weight=1.0,
            energy_x_cost=10.0,
            energy_y_cost=1.0,
            energy_z_cost=1.0,
            top_groups=1,
            src_limit=1,
            dst_limit_per_src=50,
            x_radius=2,
            y_aware=False,
            selection_mode="best",
        )

        cands = generate_candidate_moves(st, cfg)
        by_dst = {(c.dst[0], c.dst[1]): c for c in cands}
        self.assertIn((1, 0), by_dst)
        self.assertIn((0, 4), by_dst)

        x_move = by_dst[(1, 0)]  # dx=1, dy=0
        y_move = by_dst[(0, 4)]  # dx=0, dy=4, same time cost as dx=1
        self.assertAlmostEqual(x_move.delta_time, y_move.delta_time, places=9)
        self.assertGreater(x_move.delta_energy, y_move.delta_energy)
        self.assertGreater(x_move.score, y_move.score)

    def test_group_retrieval_term_biases_towards_drop_for_active_group(self) -> None:
        X, Y, H = 1, 3, 1
        yard: List[List[List[int]]] = [[[] for _ in range(Y)] for _ in range(X)]
        yard[0][1] = [0]
        st = State.build_from_yard(X=X, Y=Y, H=H, yard=yard, group=[0])
        st.crane_pos = (0, 1)
        st.time_used = 0.0

        cfg_base = OptimizerConfig(
            seed=1,
            lam=0.0,
            energy_weight=0.0,
            top_groups=1,
            src_limit=1,
            dst_limit_per_src=10,
            x_radius=0,
            y_aware=False,
            group_retrieval_weight=0.0,
            selection_mode="best",
        )
        cands_base = generate_candidate_moves(st, cfg_base)
        self.assertGreaterEqual(len(cands_base), 2)
        self.assertEqual(cands_base[0].dst, (0, 0))

        cfg_group = OptimizerConfig(
            **{
                **cfg_base.__dict__,
                "drop_x": 0,
                "drop_y": 2,
                "retrieval_time_weight": 1.0,
                "retrieval_energy_weight": 0.0,
                "group_blocker_penalty": 0.0,
                "group_retrieval_weight": 10.0,
                "active_group": 0,
            }
        )
        cands_group = generate_candidate_moves(st, cfg_group)
        self.assertGreaterEqual(len(cands_group), 2)
        self.assertEqual(cands_group[0].dst, (0, 2))
        self.assertLess(cands_group[0].delta_group_retrieval, 0.0)

    def test_container_priority_term_biases_prioritized_container_towards_drop(self) -> None:
        X, Y, H = 1, 3, 1
        yard: List[List[List[int]]] = [[[] for _ in range(Y)] for _ in range(X)]
        yard[0][1] = [0]
        st = State.build_from_yard(X=X, Y=Y, H=H, yard=yard, group=[0])
        st.crane_pos = (0, 1)
        st.time_used = 0.0

        cfg_base = OptimizerConfig(
            seed=3,
            lam=0.0,
            energy_weight=0.0,
            top_groups=1,
            src_limit=1,
            dst_limit_per_src=10,
            x_radius=0,
            y_aware=False,
            container_retrieval_weight=0.0,
            selection_mode="best",
        )
        cands_base = generate_candidate_moves(st, cfg_base)
        self.assertGreaterEqual(len(cands_base), 2)
        self.assertEqual(cands_base[0].dst, (0, 0))

        cfg_priority = OptimizerConfig(
            **{
                **cfg_base.__dict__,
                "drop_x": 0,
                "drop_y": 2,
                "retrieval_time_weight": 1.0,
                "retrieval_energy_weight": 0.0,
                "container_blocker_penalty": 0.0,
                "container_retrieval_weight": 10.0,
                "container_priority_map": {0: 1.0},
            }
        )
        cands_priority = generate_candidate_moves(st, cfg_priority)
        self.assertGreaterEqual(len(cands_priority), 2)
        self.assertEqual(cands_priority[0].dst, (0, 2))
        self.assertLess(cands_priority[0].delta_container_priority, 0.0)


if __name__ == "__main__":
    unittest.main()
