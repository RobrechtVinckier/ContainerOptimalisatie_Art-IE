from __future__ import annotations

import argparse
import random
from typing import List

try:
    from .optimizer import OptimizerConfig, TabuMetrics, greedy_plan, tabu_improve
    from .state import State
except ImportError:  # pragma: no cover - CLI fallback
    from optimizer import OptimizerConfig, TabuMetrics, greedy_plan, tabu_improve
    from state import State


def make_random_instance(X: int, Y: int, H: int, groups: int, per_group: int, seed: int) -> State:
    rng = random.Random(seed)
    n = groups * per_group
    capacity = X * Y * H
    if n > capacity:
        raise ValueError(f"Too many containers: {n} > yard capacity {capacity}")

    group: List[int] = []
    for g in range(groups):
        group.extend([g] * per_group)

    # shuffle container IDs deterministically
    ids = list(range(n))
    rng.shuffle(ids)

    yard: List[List[List[int]]] = [[[] for _ in range(Y)] for _ in range(X)]

    # fill stacks randomly but respecting capacity
    coords = [(x, y) for x in range(X) for y in range(Y)]
    for cid in ids:
        while True:
            x, y = rng.choice(coords)
            if len(yard[x][y]) < H:
                yard[x][y].append(cid)
                break

    # build state and randomize crane start (optional; keep deterministic)
    state = State.build_from_yard(X=X, Y=Y, H=H, yard=yard, group=group)
    state.crane_pos = (0, 0)
    state.time_used = 0.0
    return state


def print_group_metrics(state: State, max_groups: int = 12) -> None:
    G = state.num_groups()
    show = min(G, max_groups)
    order = sorted(range(G), key=lambda g: (-state.group_spread(g), g))
    print("Top group spreads:")
    for g in order[:show]:
        print(
            f"  g={g:02d} spread={state.spread[g]:7.2f} "
            f"x[{state.xmin[g]},{state.xmax[g]}] y[{state.ymin[g]},{state.ymax[g]}]"
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Night simulator + optimizer for 3D yard rehandling.")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--X", type=int, default=10)
    p.add_argument("--Y", type=int, default=5)
    p.add_argument("--H", type=int, default=4)
    p.add_argument("--groups", type=int, default=8)
    p.add_argument("--per-group", type=int, default=15)

    p.add_argument("--lambda", dest="lam", type=float, default=1.0)
    p.add_argument("--stack-top-mismatch-weight", type=float, default=0.0)
    p.add_argument("--stack-rehandle-weight", type=float, default=0.0)
    p.add_argument("--stack-impurity-weight", type=float, default=0.0)
    p.add_argument("--buried-foreign-weight", type=float, default=0.0)
    p.add_argument("--group-fragmentation-weight", type=float, default=0.0)
    p.add_argument("--quality-tie-eps", type=float, default=1e-9)
    p.add_argument("--operational-weight", type=float, default=1.0)
    p.add_argument("--operational-normalizer", type=float, default=60.0)
    p.add_argument("--energy-weight", type=float, default=1.0)
    p.add_argument("--energy-x-cost", type=float, default=10.0)
    p.add_argument("--energy-y-cost", type=float, default=1.0)
    p.add_argument("--energy-z-cost", type=float, default=1.0)
    p.add_argument("--night-budget", type=float, default=28800.0)

    p.add_argument("--top-groups", type=int, default=5)
    p.add_argument("--src-limit", type=int, default=40)
    p.add_argument("--dst-limit", type=int, default=30)
    p.add_argument("--x-radius", type=int, default=2)
    p.add_argument("--y-radius", type=int, default=1)
    p.add_argument("--y-aware", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--max-expensive-axis-src-delta", type=int, default=4)
    p.add_argument("--max-expensive-axis-move-delta", type=int, default=3)
    p.add_argument("--diversify-period", type=int, default=0)
    p.add_argument("--diversify-random-dsts", type=int, default=0)

    p.add_argument("--tabu-iters", type=int, default=1500)
    p.add_argument("--tabu-len", type=int, default=200)
    p.add_argument("--tabu-mode", choices=["cid_edge", "edge", "edge_reverse", "combined"], default="combined")
    p.add_argument("--selection-mode", choices=["best", "topk_best_nontabu", "topk_deterministic"], default="topk_best_nontabu")
    p.add_argument("--top-k", type=int, default=30)
    p.add_argument("--non-improving-penalty", type=float, default=1.0)
    p.add_argument("--plateau-iters", type=int, default=120)
    p.add_argument("--shake-enabled", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--reactive-tabu-enabled", action=argparse.BooleanOptionalAction, default=False)
    p.add_argument("--tabu-len-min", type=int, default=200)
    p.add_argument("--tabu-len-max", type=int, default=200)
    p.add_argument("--tabu-reactive-window", type=int, default=80)
    p.add_argument("--tabu-reverse-rate-threshold", type=float, default=0.12)
    p.add_argument("--tabu-repeat-rate-threshold", type=float, default=0.35)
    p.add_argument("--tabu-stagnation-rate-threshold", type=float, default=0.04)
    p.add_argument("--tabu-len-adjust-step", type=int, default=10)
    p.add_argument("--frequency-edge-weight", type=float, default=0.0)
    p.add_argument("--frequency-stack-weight", type=float, default=0.0)
    p.add_argument("--frequency-container-weight", type=float, default=0.0)
    p.add_argument("--elite-pool-size", type=int, default=4)
    p.add_argument("--elite-restart-enabled", action=argparse.BooleanOptionalAction, default=False)
    p.add_argument("--path-relink-enabled", action=argparse.BooleanOptionalAction, default=False)
    p.add_argument("--path-relink-steps", type=int, default=6)

    p.add_argument("--metrics", action="store_true", help="Print lightweight Tabu run metrics.")
    p.add_argument("--metrics-sample-every", type=int, default=50)

    args = p.parse_args()

    state0 = make_random_instance(args.X, args.Y, args.H, args.groups, args.per_group, args.seed)
    cfg = OptimizerConfig(
        seed=args.seed,
        night_budget_s=args.night_budget,
        lam=args.lam,
        stack_top_mismatch_weight=args.stack_top_mismatch_weight,
        stack_rehandle_weight=args.stack_rehandle_weight,
        stack_impurity_weight=args.stack_impurity_weight,
        buried_foreign_weight=args.buried_foreign_weight,
        group_fragmentation_weight=args.group_fragmentation_weight,
        quality_tie_eps=args.quality_tie_eps,
        operational_weight=args.operational_weight,
        operational_normalizer=args.operational_normalizer,
        energy_weight=args.energy_weight,
        energy_x_cost=args.energy_x_cost,
        energy_y_cost=args.energy_y_cost,
        energy_z_cost=args.energy_z_cost,
        top_groups=args.top_groups,
        src_limit=args.src_limit,
        dst_limit_per_src=args.dst_limit,
        x_radius=args.x_radius,
        y_radius=args.y_radius,
        y_aware=args.y_aware,
        max_expensive_axis_src_delta=args.max_expensive_axis_src_delta,
        max_expensive_axis_move_delta=args.max_expensive_axis_move_delta,
        diversify_period=args.diversify_period,
        diversify_random_dsts=args.diversify_random_dsts,
        tabu_iters=args.tabu_iters,
        tabu_len=args.tabu_len,
        tabu_mode=args.tabu_mode,
        top_k=args.top_k,
        selection_mode=args.selection_mode,
        non_improving_penalty=args.non_improving_penalty,
        plateau_iters=args.plateau_iters,
        shake_enabled=args.shake_enabled,
        reactive_tabu_enabled=args.reactive_tabu_enabled,
        tabu_len_min=args.tabu_len_min,
        tabu_len_max=args.tabu_len_max,
        tabu_reactive_window=args.tabu_reactive_window,
        tabu_reverse_rate_threshold=args.tabu_reverse_rate_threshold,
        tabu_repeat_rate_threshold=args.tabu_repeat_rate_threshold,
        tabu_stagnation_rate_threshold=args.tabu_stagnation_rate_threshold,
        tabu_len_adjust_step=args.tabu_len_adjust_step,
        frequency_edge_weight=args.frequency_edge_weight,
        frequency_stack_weight=args.frequency_stack_weight,
        frequency_container_weight=args.frequency_container_weight,
        elite_pool_size=args.elite_pool_size,
        elite_restart_enabled=args.elite_restart_enabled,
        path_relink_enabled=args.path_relink_enabled,
        path_relink_steps=args.path_relink_steps,
        metrics_sample_every=args.metrics_sample_every,
    )

    start_cost = state0.cluster_cost()
    print(f"Initial cluster cost: {start_cost:.2f}")
    print_group_metrics(state0)

    # Greedy
    state_g = state0.clone()
    greedy_moves = greedy_plan(state_g, cfg)
    greedy_cost = state_g.cluster_cost()
    print("\nGreedy result")
    print(f"  moves: {len(greedy_moves)}")
    print(f"  time_used: {state_g.time_used:.2f}s / {cfg.night_budget_s:.2f}s")
    print(f"  cluster_cost: {start_cost:.2f} -> {greedy_cost:.2f}  (delta {greedy_cost - start_cost:+.2f})")

    # Tabu improve from greedy state
    state_t = state_g.clone()
    metrics = TabuMetrics() if args.metrics else None
    tabu_moves, best_state = tabu_improve(state_t, cfg, metrics=metrics)
    best_cost = best_state.cluster_cost()

    print("\nTabu result (best found during search)")
    print(f"  moves_applied_in_search: {len(tabu_moves)}")
    print(f"  best_time_used: {best_state.time_used:.2f}s / {cfg.night_budget_s:.2f}s")
    print(f"  best_cluster_cost: {start_cost:.2f} -> {best_cost:.2f}  (delta {best_cost - start_cost:+.2f})")
    print_group_metrics(best_state)

    if metrics is not None:
        print("\nTabu metrics")
        print(f"  total_search_moves: {metrics.total_search_moves}")
        print(f"  unique_containers_moved: {metrics.unique_containers_moved}")
        print(f"  immediate_reversals: {metrics.immediate_reversals}")
        print(f"  repeated_edges: {metrics.repeated_edges}")
        print(f"  stop_reason: {metrics.stop_reason}")
        print(f"  restarts: {metrics.restart_count}")
        print(f"  relink_steps_applied: {metrics.relink_steps_applied}")
        if metrics.best_cost_curve:
            first_it, first_cost = metrics.best_cost_curve[0]
            last_it, last_cost = metrics.best_cost_curve[-1]
            print(
                "  best_cost_curve:"
                f" samples={len(metrics.best_cost_curve)}"
                f" first=({first_it}, {first_cost:.2f})"
                f" last=({last_it}, {last_cost:.2f})"
            )
        if metrics.tabu_len_curve:
            first_it, first_len = metrics.tabu_len_curve[0]
            last_it, last_len = metrics.tabu_len_curve[-1]
            print(
                "  tabu_len_curve:"
                f" samples={len(metrics.tabu_len_curve)}"
                f" first=({first_it}, {first_len})"
                f" last=({last_it}, {last_len})"
            )

    # Output move list (compact)
    print("\nMove list (first 30):")
    for m in tabu_moves[:30]:
        print(f"  t={m.t_start:8.2f}->{m.t_end:8.2f}  cid={m.container_id:4d}  {m.src}->{m.dst}")
    if len(tabu_moves) > 30:
        print(f"  ... ({len(tabu_moves) - 30} more)")


if __name__ == "__main__":
    main()
