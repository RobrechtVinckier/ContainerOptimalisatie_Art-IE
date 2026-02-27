# state.py
"""
3D Yard Night Rehandling Simulator (Python 3.11, no external services)

Files in this mini-project:
- state.py        : data model + fast clustering cost + move apply + delta cost
- optimizer.py    : greedy planner + tabu improver
- main.py         : CLI runner (random instance -> plan -> print summary)
- tests/test_delta.py : unit tests (constraints + delta correctness)

Problem summary
---------------
- Yard grid: X by Y stacks, each stack is LIFO with max height H.
- Only the TOP container of a stack can be moved.
- Crane time is horizontal travel only:
    T(a->b) = 2*|dx| + 0.5*|dy|  (vX=0.5m/s, vY=2m/s, spacing=1m)
- Objective: clustering without fixed zones:
    Spread(g) = 2*(xmax-xmin) + 0.5*(ymax-ymin)
    ClusterCost = sum_g Spread(g)
- Planner chooses moves until the 8h night budget is exhausted or no useful moves.

Engineering notes
-----------------
- Deterministic: random seed controls instance generation and tie-breaking.
- Robust delta: delta_cluster_cost_for_move uses safe O(X+Y) scan with virtual counts.
- No global state; everything lives in a State object.

Run
---
python3 -m main --seed 1 --groups 8 --per-group 15 --lambda 1.0 --tabu-iters 1500

Tests
-----
python3 -m unittest -v
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

XY = Tuple[int, int]


def travel_time(a: XY, b: XY) -> float:
    """Horizontal travel time in seconds with grid spacing 1m."""
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    return 2.0 * dx + 0.5 * dy


@dataclass(frozen=True)
class Move:
    container_id: int
    src: XY
    dst: XY
    t_start: float
    t_end: float

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start


@dataclass
class State:
    X: int
    Y: int
    H: int
    # yard[x][y] = list of container IDs (bottom -> top)
    yard: List[List[List[int]]]
    # group[container_id] = group index
    group: List[int]
    # pos[container_id] = (x, y) current stack coordinates
    pos: List[XY]

    crane_pos: XY = (0, 0)
    time_used: float = 0.0

    # counts by group per coordinate axis
    count_x: List[List[int]] = field(default_factory=list)  # [g][x]
    count_y: List[List[int]] = field(default_factory=list)  # [g][y]

    # cached bounds and spreads per group (updated incrementally)
    xmin: List[int] = field(default_factory=list)
    xmax: List[int] = field(default_factory=list)
    ymin: List[int] = field(default_factory=list)
    ymax: List[int] = field(default_factory=list)
    spread: List[float] = field(default_factory=list)

    def num_groups(self) -> int:
        return max(self.group) + 1 if self.group else 0

    def stack(self, xy: XY) -> List[int]:
        x, y = xy
        return self.yard[x][y]

    def top(self, xy: XY) -> Optional[int]:
        st = self.stack(xy)
        return st[-1] if st else None

    def can_move(self, src: XY, dst: XY) -> bool:
        if src == dst:
            return False
        sx, sy = src
        dx, dy = dst
        if not (0 <= sx < self.X and 0 <= sy < self.Y):
            return False
        if not (0 <= dx < self.X and 0 <= dy < self.Y):
            return False
        if not self.stack(src):
            return False
        if len(self.stack(dst)) >= self.H:
            return False
        return True

    def move_time(self, src: XY, dst: XY) -> float:
        return travel_time(self.crane_pos, src) + travel_time(src, dst)

    # -------------------------
    # Cluster cost computations
    # -------------------------
    @staticmethod
    def _spread_from_bounds(xmin: int, xmax: int, ymin: int, ymax: int) -> float:
        return 2.0 * (xmax - xmin) + 0.5 * (ymax - ymin)

    def cluster_cost(self) -> float:
        return float(sum(self.spread))

    def compute_cluster_cost_bruteforce(self) -> float:
        """Recompute full ClusterCost from container positions (slow, for tests)."""
        G = self.num_groups()
        xs: List[List[int]] = [[] for _ in range(G)]
        ys: List[List[int]] = [[] for _ in range(G)]
        for cid, (x, y) in enumerate(self.pos):
            g = self.group[cid]
            xs[g].append(x)
            ys[g].append(y)
        total = 0.0
        for g in range(G):
            if not xs[g]:
                continue
            total += self._spread_from_bounds(min(xs[g]), max(xs[g]), min(ys[g]), max(ys[g]))
        return total

    def group_spread(self, g: int) -> float:
        return self.spread[g]

    def group_center(self, g: int) -> Tuple[float, float]:
        """Center of mass in (x,y) using counts, deterministic."""
        total = sum(self.count_x[g])
        if total <= 0:
            return (0.0, 0.0)
        cx = 0.0
        cy = 0.0
        for x in range(self.X):
            cx += x * self.count_x[g][x]
        for y in range(self.Y):
            cy += y * self.count_y[g][y]
        return (cx / total, cy / total)

    # -------------------------
    # Bounds helpers
    # -------------------------
    def _recompute_bounds_1d_from_counts(self, counts: Sequence[int]) -> Tuple[int, int]:
        i_min = None
        i_max = None
        for i, c in enumerate(counts):
            if c > 0:
                i_min = i if i_min is None else i_min
                i_max = i
        if i_min is None or i_max is None:
            return (0, 0)
        return (i_min, i_max)

    def _bounds_after_1d_move(self, counts: Sequence[int], dec_idx: int, inc_idx: int) -> Tuple[int, int]:
        """
        Compute bounds (min,max) after applying a virtual update:
          counts[dec_idx] -= 1, counts[inc_idx] += 1.

        Safe O(n) scan (n = X or Y). With X<=10, Y<=5 this is extremely cheap and robust.
        """
        n = len(counts)
        i_min = None
        i_max = None
        for i in range(n):
            v = counts[i]
            if i == dec_idx:
                v -= 1
            if i == inc_idx:
                v += 1
            if v > 0:
                if i_min is None:
                    i_min = i
                i_max = i
        # In normal usage groups won't become empty; fallback defensively.
        if i_min is None or i_max is None:
            return (0, 0)
        return (i_min, i_max)

    def delta_cluster_cost_for_move(self, container_id: int, src: XY, dst: XY) -> float:
        """
        Delta ClusterCost if container_id (group g) moves from src to dst.
        Only affects group g bounds. Uses safe O(X+Y) scan with virtual counts.
        """
        if src == dst:
            return 0.0

        g = self.group[container_id]
        sx, sy = src
        dx, dy = dst

        # If same coordinate on an axis, that axis bounds do not change.
        if sx == dx:
            new_xmin, new_xmax = self.xmin[g], self.xmax[g]
        else:
            new_xmin, new_xmax = self._bounds_after_1d_move(self.count_x[g], dec_idx=sx, inc_idx=dx)

        if sy == dy:
            new_ymin, new_ymax = self.ymin[g], self.ymax[g]
        else:
            new_ymin, new_ymax = self._bounds_after_1d_move(self.count_y[g], dec_idx=sy, inc_idx=dy)

        new_spread = self._spread_from_bounds(new_xmin, new_xmax, new_ymin, new_ymax)
        return new_spread - self.spread[g]

    # -------------------------
    # Move application
    # -------------------------
    def apply_move(self, src: XY, dst: XY) -> int:
        """
        Apply a legal top-of-stack move, updating yard/pos/counts/bounds/spreads/crane/time.
        Returns container_id moved.
        Raises ValueError on constraint violation.
        """
        if not self.can_move(src, dst):
            raise ValueError(f"Illegal move {src}->{dst}")

        src_stack = self.stack(src)
        dst_stack = self.stack(dst)
        if not src_stack:
            raise ValueError("Source stack empty")
        if len(dst_stack) >= self.H:
            raise ValueError("Destination stack full")

        cid = src_stack[-1]
        g = self.group[cid]

        # Compute move time and update time/crane
        dt = self.move_time(src, dst)
        self.time_used += dt
        self.crane_pos = dst

        # Pop/push
        src_stack.pop()
        dst_stack.append(cid)

        # Update pos
        self.pos[cid] = dst

        # Update counts
        sx, sy = src
        dx, dy = dst
        self.count_x[g][sx] -= 1
        self.count_y[g][sy] -= 1
        self.count_x[g][dx] += 1
        self.count_y[g][dy] += 1

        # Update bounds + spread (small scan; robust)
        self.xmin[g], self.xmax[g] = self._recompute_bounds_1d_from_counts(self.count_x[g])
        self.ymin[g], self.ymax[g] = self._recompute_bounds_1d_from_counts(self.count_y[g])
        self.spread[g] = self._spread_from_bounds(self.xmin[g], self.xmax[g], self.ymin[g], self.ymax[g])

        return cid

    def clone(self) -> "State":
        """Deep-ish copy (yard stacks copied), deterministic and safe for local search."""
        yard_copy: List[List[List[int]]] = [
            [list(self.yard[x][y]) for y in range(self.Y)] for x in range(self.X)
        ]
        return State(
            X=self.X,
            Y=self.Y,
            H=self.H,
            yard=yard_copy,
            group=list(self.group),
            pos=list(self.pos),
            crane_pos=self.crane_pos,
            time_used=self.time_used,
            count_x=[list(row) for row in self.count_x],
            count_y=[list(row) for row in self.count_y],
            xmin=list(self.xmin),
            xmax=list(self.xmax),
            ymin=list(self.ymin),
            ymax=list(self.ymax),
            spread=list(self.spread),
        )

    @classmethod
    def build_from_yard(cls, X: int, Y: int, H: int, yard: List[List[List[int]]], group: List[int]) -> "State":
        n = len(group)
        pos: List[XY] = [(0, 0)] * n

        for x in range(X):
            for y in range(Y):
                for cid in yard[x][y]:
                    pos[cid] = (x, y)

        G = max(group) + 1 if group else 0
        count_x = [[0 for _ in range(X)] for _ in range(G)]
        count_y = [[0 for _ in range(Y)] for _ in range(G)]
        for cid, (x, y) in enumerate(pos):
            g = group[cid]
            count_x[g][x] += 1
            count_y[g][y] += 1

        xmin = [0] * G
        xmax = [0] * G
        ymin = [0] * G
        ymax = [0] * G
        spread = [0.0] * G

        tmp = cls(X=X, Y=Y, H=H, yard=yard, group=group, pos=pos)
        tmp.count_x = count_x
        tmp.count_y = count_y
        for g in range(G):
            xmin[g], xmax[g] = tmp._recompute_bounds_1d_from_counts(count_x[g])
            ymin[g], ymax[g] = tmp._recompute_bounds_1d_from_counts(count_y[g])
            spread[g] = tmp._spread_from_bounds(xmin[g], xmax[g], ymin[g], ymax[g])
        tmp.xmin, tmp.xmax, tmp.ymin, tmp.ymax, tmp.spread = xmin, xmax, ymin, ymax, spread
        return tmp