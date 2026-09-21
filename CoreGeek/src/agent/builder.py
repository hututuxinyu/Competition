from __future__ import annotations

from typing import Any

from .grid import next_step
from .memory import Memory
from .protocol import (
    Pos,
    Turn,
    Unit,
    WALL,
    WALL_MATERIAL,
    WEAPON_BUILD_COST,
    build_command,
    distance,
    move_command,
    station_footprint,
)

TOWER_LOADOUT = ("rocket", "rocket", "rocket")  # 全火箭(全图溅射+多目标)，对手共性最优选型
STONE_BATCH = 6
WALL_LAYERS = (2, 3)  # 双层围墙：distance2 主环 + distance3 外环

_NEIGHBOUR_STEPS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


def run(
    turn: Turn,
    mem: Memory,
    commands: dict[int, dict[str, Any]],
    assigned: set[int],
    claimed: set[Pos],
    deadline: float,
) -> None:
    """白天建造调度：建塔优先，其次建墙。"""
    import time
    sites = tower_sites(turn)
    order = wall_order(turn)
    standing_towers = {u.pos for u in turn.weapons()}
    standing_walls = {u.pos for u in turn.walls()}
    occupied = turn.occupied_cells()
    towers_missing = [p for p in sites if p not in standing_towers]
    walls_missing = [p for p in order if p not in standing_walls]
    free_towers = [p for p in towers_missing if p not in occupied]
    free_walls = [p for p in walls_missing if p not in occupied]

    for worker in turn.workers():
        if worker.unit_id in assigned:
            continue
        if time.monotonic() > deadline:
            break
        cmd = plan_build_tower(turn, worker, sites, free_towers, claimed)
        if cmd is not None:
            commands[worker.unit_id] = cmd
            assigned.add(worker.unit_id)
            continue
        cmd = plan_build_wall(turn, worker, free_walls, claimed)
        if cmd is not None:
            commands[worker.unit_id] = cmd
            assigned.add(worker.unit_id)
            continue
        # 无建造任务 → 采矿（由 brain 兜底处理）


def plan_build_tower(
    turn: Turn,
    worker: Unit,
    sites: tuple[Pos, ...],
    towers_missing: list[Pos],
    claimed: set[Pos],
) -> dict[str, Any] | None:
    if not towers_missing or turn.gold < WEAPON_BUILD_COST:
        return None
    for index, site in enumerate(sites):
        if site not in towers_missing or site in claimed:
            continue
        return _build_or_walk(turn, worker, site, TOWER_LOADOUT[index], claimed)
    return None


def plan_build_wall(
    turn: Turn,
    worker: Unit,
    walls_missing: list[Pos],
    claimed: set[Pos],
) -> dict[str, Any] | None:
    """有石头时：紧邻墙位→建墙；墙位≤3格→走过去；否则不主动走远路。"""
    if not walls_missing:
        return None
    stones = worker.item_count(WALL_MATERIAL)
    if stones <= 0:
        return None
    # 找最近墙位
    nearest: Pos | None = None
    nearest_dist = 10 ** 9
    for site in walls_missing:
        if site in claimed:
            continue
        d = distance(worker.pos, site)
        if d < nearest_dist:
            nearest_dist = d
            nearest = site
    if nearest is None:
        return None
    # 紧邻→建墙
    if nearest_dist <= 1:
        claimed.add(nearest)
        return build_command(nearest, WALL)
    # ≤5格→走过去（U型墙北面在y=19，距基地4-5格）
    if nearest_dist <= 5:
        return _build_or_walk(turn, worker, nearest, WALL, claimed)
    return None  # 太远，让采集逻辑处理移动


def tower_sites(turn: Turn) -> tuple[Pos, ...]:
    station = turn.station()
    if station is None:
        return ()
    footprint = station_footprint(station.pos)
    # distance1 优先；若无可建格(基地旁被占满)则扩大到 distance2
    for radius in (1, 2):
        cells = [p for p in _cells_at_distance(station.pos, radius) if turn.land(p)]
        cells.sort(key=lambda p: (_footprint_distance(p, footprint), p.x, p.y))
        if cells:
            return tuple(cells[:3])
    return ()


def wall_order(turn: Turn) -> tuple[Pos, ...]:
    """U型围墙：远侧(ymin-4) + 东侧(xmax+1) + 站位西侧(ymax, x<xmin)。
    对手共性布局：14墙，三面包围，西侧开放（靠塔覆盖）。"""
    station = turn.station()
    if station is None:
        return ()
    footprint = station_footprint(station.pos)
    xs = [p.x for p in footprint]
    ys = [p.y for p in footprint]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    fp_set = set(footprint)
    order: list[Pos] = []

    # 1. 远侧横墙：y = ymin - 4，x 从 xmin-3 到 xmax+1
    far_y = ymin - 4
    for x in range(xmin - 3, xmax + 2):
        order.append(Pos(x, far_y))

    # 2. 东侧纵墙：x = xmax + 1，y 从 far_y+1 到 ymax
    east_x = xmax + 1
    for y in range(far_y + 1, ymax + 1):
        order.append(Pos(east_x, y))

    # 3. 站位西侧横墙：y = ymax，x 从 xmin-3 到 xmin-1（排除站位）
    for x in range(xmin - 3, xmin):
        order.append(Pos(x, ymax))

    # 去重 + 过滤障碍/非land，排除基地footprint
    seen: set[Pos] = set()
    result: list[Pos] = []
    for p in order:
        if p in seen or p in fp_set:
            continue
        if turn.land(p):
            seen.add(p)
            result.append(p)
    return tuple(result)


def _ring_layer(station_pos: Pos, layer: int) -> list[Pos]:
    footprint = station_footprint(station_pos)
    xs = [p.x for p in footprint]
    ys = [p.y for p in footprint]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    d = layer
    order = [
        # 上边
        *(Pos(x, ymin - d) for x in range(xmax + d, xmin - d - 1, -1)),
        # 左边
        *(Pos(xmin - d, y) for y in range(ymin - d + 1, ymax + d)),
        # 下边
        *(Pos(x, ymax + d) for x in range(xmin - d, xmax + d + 1)),
        # 右边
        *(Pos(xmax + d, y) for y in range(ymax + d - 1, ymin - d, -1)),
    ]
    entrance = Pos(xmax + d, ymin - d + 1)
    return [p for p in order if p != entrance]


def _build_or_walk(
    turn: Turn,
    worker: Unit,
    target: Pos,
    name: str,
    claimed: set[Pos],
) -> dict[str, Any] | None:
    if worker.pos != target and distance(worker.pos, target) <= 1:
        claimed.add(target)
        return build_command(target, name)
    step = _step_toward(turn, worker, target, claimed)
    if step is not None:
        return move_command(step)
    return None


def _step_toward(
    turn: Turn,
    worker: Unit,
    target: Pos,
    claimed: set[Pos],
) -> Pos | None:
    for stand in _stand_cells(turn, worker, target, claimed):
        if stand == worker.pos:
            return None
        step = next_step(turn, worker, stand)
        if step is None or step in claimed:
            continue
        claimed.add(step)
        return step
    return None


def _stand_cells(
    turn: Turn,
    worker: Unit,
    target: Pos,
    claimed: set[Pos],
) -> list[Pos]:
    blocked = turn.blocked(worker)
    cells = [
        p for p in _neighbours(target)
        if turn.land(p)
        and p not in blocked
        and (p == worker.pos or p not in claimed)
    ]
    cells.sort(key=lambda p: (distance(worker.pos, p), p.x, p.y))
    return cells


def _cells_at_distance(station_pos: Pos, radius: int) -> tuple[Pos, ...]:
    footprint = station_footprint(station_pos)
    xs = [p.x for p in footprint]
    ys = [p.y for p in footprint]
    cells = []
    for x in range(min(xs) - radius, max(xs) + radius + 1):
        for y in range(min(ys) - radius, max(ys) + radius + 1):
            pos = Pos(x, y)
            if pos in footprint:
                continue
            if _footprint_distance(pos, footprint) == radius:
                cells.append(pos)
    return tuple(cells)


def _footprint_distance(pos: Pos, footprint: tuple[Pos, ...]) -> int:
    if not footprint:
        return 0
    return min(distance(pos, cell) for cell in footprint)


def _neighbours(pos: Pos) -> tuple[Pos, ...]:
    return tuple(
        Pos(pos.x + dx, pos.y + dy) for dx, dy in _NEIGHBOUR_STEPS
    )
