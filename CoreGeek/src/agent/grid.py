from heapq import heappop, heappush
from itertools import count

from .protocol import Pos, Turn, Unit, distance

_STEPS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


def next_step(turn: Turn, moving: Unit, goal: Pos) -> Pos | None:
    blocked = turn.blocked(moving)
    order = count()
    frontier: list[tuple[int, int, int, Pos]] = [
        (distance(moving.pos, goal), 0, next(order), moving.pos)
    ]
    came_from: dict[Pos, Pos] = {}
    best = {moving.pos: 0}
    seen: set[Pos] = set()

    while frontier:
        _, cost, _, current = heappop(frontier)
        if current in seen:
            continue
        if current == goal:
            return _first_step(came_from, moving.pos, goal)
        seen.add(current)
        for dx, dy in _STEPS:
            step = Pos(current.x + dx, current.y + dy)
            if step in blocked or not turn.land(step):
                continue
            new_cost = cost + 1
            if new_cost >= best.get(step, new_cost + 1):
                continue
            best[step] = new_cost
            came_from[step] = current
            heappush(
                frontier,
                (
                    new_cost + distance(step, goal),
                    new_cost,
                    next(order),
                    step,
                ),
            )
    return None


def next_step_to_adjacent(
    turn: Turn, moving: Unit, target: Pos, claimed: set[Pos] | None = None
) -> Pos | None:
    """寻路到 target 旁的可站立格（target 本身可能是障碍：矿/任务点/商店/宝藏点）。
    返回下一步 Pos 或 None。按距离取最近的可达邻居。"""
    blocked = turn.blocked(moving)
    stand_cells: list[Pos] = []
    for dx, dy in _STEPS:
        p = Pos(target.x + dx, target.y + dy)
        if turn.land(p) and p not in blocked:
            stand_cells.append(p)
    stand_cells.sort(key=lambda p: distance(moving.pos, p))
    for stand in stand_cells:
        if stand == moving.pos:
            return None  # 已在 target 旁，无需移动
        step = next_step(turn, moving, stand)
        if step is not None and (claimed is None or step not in claimed):
            return step
    return None


def _first_step(came_from: dict[Pos, Pos], start: Pos, goal: Pos) -> Pos:
    current = goal
    while came_from[current] != start:
        current = came_from[current]
    return current
