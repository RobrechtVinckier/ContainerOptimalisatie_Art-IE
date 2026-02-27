from __future__ import annotations

import argparse
import random
from typing import List, Tuple

from optimizer import OptimizerConfig, greedy_plan, tabu_improve
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
    p.add_argument("--night-budget", type=float, default=28800.0)

    p.add_argument("--top-groups", type=int, default=5)
    p.add_argument("--src-limit", type=int, default=40)
    p.add_argument("--dst-limit", type=int, default=30)
    p.add_argument("--x-radius", type=int, default=2)

    p.add_argument("--tabu-iters", type=int, default=1500)
    p.add_argument("--tabu-len", type=int, default=200)

    args = p.parse_args()

    state0 = make_random_instance(args.X, args.Y, args.H, args.groups, args.per_group, args.seed)
    cfg = OptimizerConfig(
        night_budget_s=args.night_budget,
        lam=args.lam,
        top_groups=args.top_groups,
        src_limit=args.src_limit,
        dst_limit_per_src=args.dst_limit,
        x_radius=args.x_radius,
        tabu_iters=args.tabu_iters,
        tabu_len=args.tabu_len,
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
    tabu_moves, best_state = tabu_improve(state_t, cfg)
    best_cost = best_state.cluster_cost()

    print("\nTabu result (best found during search)")
    print(f"  moves_applied_in_search: {len(tabu_moves)}")
    print(f"  best_time_used: {best_state.time_used:.2f}s / {cfg.night_budget_s:.2f}s")
    print(f"  best_cluster_cost: {start_cost:.2f} -> {best_cost:.2f}  (delta {best_cost - start_cost:+.2f})")
    print_group_metrics(best_state)

    # Output move list (compact)
    print("\nMove list (first 30):")
    for m in tabu_moves[:30]:
        print(f"  t={m.t_start:8.2f}->{m.t_end:8.2f}  cid={m.container_id:4d}  {m.src}->{m.dst}")
    if len(tabu_moves) > 30:
        print(f"  ... ({len(tabu_moves) - 30} more)")


if __name__ == "__main__":
    main()