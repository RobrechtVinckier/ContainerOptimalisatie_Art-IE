import random
import unittest
from typing import List, Tuple

from optimizer import Candidate, OptimizerConfig, TabuMetrics, _rank_candidates, generate_candidate_moves, tabu_improve
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

    def assert_no_adjacent_inverse_pairs(self, moves: List) -> None:
        for idx in range(1, len(moves)):
            prev = moves[idx - 1]
            cur = moves[idx]
            self.assertFalse(
                prev.container_id == cur.container_id and prev.src == cur.dst and prev.dst == cur.src,
                f"Adjacent inverse pair at index {idx - 1}/{idx}: {prev} then {cur}",
            )

    def assert_no_consecutive_same_container(self, moves: List) -> None:
        for idx in range(1, len(moves)):
            self.assertNotEqual(
                moves[idx - 1].container_id,
                moves[idx].container_id,
                f"Consecutive moves for same container at {idx - 1}/{idx}",
            )

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
            tabu_mode="edge",
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

    def test_combined_output_omits_adjacent_inverse_pairs(self) -> None:
        base_state = self.make_ping_pong_state()
        cfg_combined = OptimizerConfig(
            seed=17,
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
            tabu_mode="combined",
            selection_mode="best",
            non_improving_penalty=0.0,
            plateau_iters=999,
            shake_enabled=False,
        )
        metrics = TabuMetrics()
        moves, _ = tabu_improve(base_state.clone(), cfg_combined, metrics=metrics)
        self.assert_no_adjacent_inverse_pairs(moves)
        self.assert_no_consecutive_same_container(moves)

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
        self.assert_no_adjacent_inverse_pairs(moves1)
        self.assert_no_consecutive_same_container(moves1)

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
        self.assert_no_adjacent_inverse_pairs(moves)
        self.assert_no_consecutive_same_container(moves)

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

    def test_tie_break_prefers_lower_operational_cost_within_quality_eps(self) -> None:
        st = self.make_ping_pong_state()
        cfg = OptimizerConfig(
            seed=1,
            night_budget_s=1000.0,
            quality_tie_eps=0.1,
            selection_mode="best",
        )

        # quality differs by 0.05 (<= eps): lower operational cost should win.
        a = Candidate(
            container_id=0,
            src=(0, 0),
            dst=(1, 0),
            delta_cluster=-1.05,
            delta_time=8.0,
            delta_energy=0.0,
            score=6.95,
            delta_quality=-1.05,
            operational_cost=8.0,
        )
        b = Candidate(
            container_id=1,
            src=(1, 0),
            dst=(0, 0),
            delta_cluster=-1.00,
            delta_time=2.0,
            delta_energy=0.0,
            score=1.00,
            delta_quality=-1.00,
            operational_cost=2.0,
        )
        ranked = _rank_candidates(
            st,
            cfg,
            [a, b],
            iteration=0,
            best_objective=999999.0,
            allow_non_improving=True,
            tabu_cid_edge={},
            tabu_edge={},
            tabu_reverse_edge={},
        )
        self.assertEqual(ranked[0].candidate.container_id, 1)

    def test_tie_break_keeps_quality_priority_outside_eps(self) -> None:
        st = self.make_ping_pong_state()
        cfg = OptimizerConfig(
            seed=1,
            night_budget_s=1000.0,
            quality_tie_eps=0.05,
            selection_mode="best",
        )

        # quality differs by 0.40 (> eps): better quality should win.
        better_quality = Candidate(
            container_id=0,
            src=(0, 0),
            dst=(1, 0),
            delta_cluster=-1.40,
            delta_time=9.0,
            delta_energy=0.0,
            score=7.6,
            delta_quality=-1.40,
            operational_cost=9.0,
        )
        worse_quality_low_op = Candidate(
            container_id=1,
            src=(1, 0),
            dst=(0, 0),
            delta_cluster=-1.00,
            delta_time=1.0,
            delta_energy=0.0,
            score=0.0,
            delta_quality=-1.00,
            operational_cost=1.0,
        )
        ranked = _rank_candidates(
            st,
            cfg,
            [better_quality, worse_quality_low_op],
            iteration=0,
            best_objective=999999.0,
            allow_non_improving=True,
            tabu_cid_edge={},
            tabu_edge={},
            tabu_reverse_edge={},
        )
        self.assertEqual(ranked[0].candidate.container_id, 0)


if __name__ == "__main__":
    unittest.main()
