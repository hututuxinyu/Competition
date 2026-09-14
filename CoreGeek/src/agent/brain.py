from __future__ import annotations

import logging
import time
from typing import Any

from . import adversary, builder, combat, economy, evolver, treasure
from .grid import next_step
from .memory import Memory
from .protocol import (
    DAY_ROUNDS,
    PIONEER,
    Pos,
    Response,
    ROUNDS_PER_DAY,
    Turn,
    Unit,
    distance,
    move_command,
    station_footprint,
)

LOGGER = logging.getLogger(__name__)

RESPONSE_DEADLINE = 4.5  # 秒，留 0.5s 余量给序列化/网络

_NEIGHBOUR_STEPS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)

_MEM = Memory()


def decide(payload: dict[str, Any]) -> Response:
    turn = Turn.load(payload)
    _MEM.update(turn)
    evolver.sync_task_state(turn, _MEM)
    commands: dict[int, dict[str, Any]] = {}
    prompt = ""
    execute_cmd = ""
    deadline = time.monotonic() + RESPONSE_DEADLINE
    try:
        if turn.is_day:
            _day(turn, commands, deadline)
        else:
            _night(turn, commands, deadline)
        prompt, execute_cmd = evolver.dispatch_tools(turn, _MEM)
        if not prompt and not execute_cmd:
            prompt = treasure.dispatch_llm(turn, _MEM)
    except Exception:
        LOGGER.exception("decision failed, returning partial commands")
    return Response(
        role_command_map={str(k): v for k, v in commands.items()},
        prompt=prompt,
        execute_cmd=execute_cmd,
    )


def _day(turn: Turn, commands: dict[int, dict[str, Any]], deadline: float) -> None:
    economy.update_forecast(turn, _MEM)
    claimed: set[Pos] = set()
    assigned: set[int] = set()
    sites = builder.tower_sites(turn)
    standing_towers = {u.pos for u in turn.weapons()}
    standing_walls = {u.pos for u in turn.walls()}
    occupied = turn.occupied_cells()
    towers_missing = [p for p in sites if p not in standing_towers and p not in occupied]
    walls_missing = [
        p for p in builder.wall_order(turn)
        if p not in standing_walls and p not in occupied
    ]
    for worker in turn.workers():
        if time.monotonic() > deadline:
            break
        cmd = _day_worker_action(
            turn, worker, sites, towers_missing, walls_missing, claimed,
        )
        if cmd is not None:
            commands[worker.unit_id] = cmd
            assigned.add(worker.unit_id)
    # 4. 开拓者：任务优先(evolver)，其次宝藏，无任务时走向武器（夜间准备）
    pioneer = turn.pioneer()
    if pioneer is not None and pioneer.unit_id not in assigned:
        cmd = evolver.plan_pioneer_action(turn, _MEM, pioneer, claimed)
        if cmd is None and not _MEM.is_pioneer_locked():
            cmd = treasure.plan_pioneer_treasure(turn, _MEM, pioneer, claimed)
        if cmd is not None:
            commands[pioneer.unit_id] = cmd
        elif not _MEM.is_pioneer_locked():
            _pioneer_to_tower(turn, pioneer, claimed, commands)


def _day_worker_action(
    turn: Turn,
    worker: Unit,
    sites: tuple[Pos, ...],
    towers_missing: list[Pos],
    walls_missing: list[Pos],
    claimed: set[Pos],
) -> dict[str, Any] | None:
    """单工人白天动作优先级：升级 > 卖矿 > 买券 > 建塔 > 移动到经济(卖矿换金币) > 建墙 > 采矿。
    夜晚前5回合强制回武器旁(夜间操控准备)。有矿先去卖换金币升级(比建墙更重要)。"""
    round_in_day = (turn.round_no - 1) % ROUNDS_PER_DAY
    # 夜晚前5回合：worker 停止采集/建墙，回最近武器旁(夜间操控)
    if round_in_day >= DAY_ROUNDS - 5:
        weapons = turn.weapons()
        if weapons:
            nearest = min(weapons, key=lambda w: distance(worker.pos, w.pos))
            if distance(worker.pos, nearest.pos) > 1:
                step = _step_toward(turn, worker, nearest.pos, claimed)
                if step is not None:
                    return move_command(step)
    for plan in (economy.plan_upgrade, economy.plan_sell, economy.plan_buy):
        cmd = plan(turn, worker)
        if cmd is not None:
            return cmd
    cmd = adversary.plan_summon(turn, _MEM, worker)
    if cmd is not None:
        return cmd
    cmd = builder.plan_build_tower(turn, worker, sites, towers_missing, claimed)
    if cmd is not None:
        return cmd
    cmd = economy.plan_move_to_economy(turn, worker, claimed)
    if cmd is not None:
        return cmd
    cmd = builder.plan_build_wall(turn, worker, walls_missing, claimed)
    if cmd is not None:
        return cmd
    return economy.plan_collect(turn, worker, _MEM, claimed)


def _pioneer_to_tower(
    turn: Turn, pioneer: Unit, claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> None:
    """无任务时开拓者走向最近武器（夜间操控准备）。"""
    weapons = turn.weapons()
    if not weapons:
        return
    nearest = min(weapons, key=lambda w: distance(pioneer.pos, w.pos))
    if distance(pioneer.pos, nearest.pos) <= 1:
        return
    step = _step_toward(turn, pioneer, nearest.pos, claimed)
    if step is not None:
        commands[pioneer.unit_id] = move_command(step)


def _night(turn: Turn, commands: dict[int, dict[str, Any]], deadline: float) -> None:
    claimed: set[Pos] = set()
    for role, tower in _tower_pairs(turn):
        if time.monotonic() > deadline:
            break
        if distance(role.pos, tower.pos) <= 1:
            # 已在武器旁：combat 决策道具/攻击
            combat.act_at_tower(turn, role, tower, commands)
            continue
        # 碰撞规避：走向武器，claimed 防止多角色争同一步
        step = _step_toward(turn, role, tower.pos, claimed)
        if step is not None:
            commands[role.unit_id] = move_command(step)


def _tower_pairs(turn: Turn) -> tuple[tuple[Unit, Unit], ...]:
    """角色-武器就近配对：每个武器配最近的未分配角色（贪心）。"""
    weapons = turn.weapons()
    controllable = turn.controllable()
    if not weapons or not controllable:
        return ()
    assigned: set[int] = set()
    pairs: list[tuple[Unit, Unit]] = []
    for tower in weapons:
        best: Unit | None = None
        best_dist = 10 ** 9
        for role in controllable:
            if role.unit_id in assigned:
                continue
            d = distance(role.pos, tower.pos)
            if d < best_dist:
                best_dist = d
                best = role
        if best is not None:
            assigned.add(best.unit_id)
            pairs.append((best, tower))
    return tuple(pairs)


def _attack_target(turn: Turn, tower: Unit) -> Pos | None:
    # 保留供回归测试/兼容；combat.select_targets 已取代
    reach = tower.range_of_attack()
    targets = [
        robot for robot in turn.robots
        if robot.health > 0 and distance(tower.pos, robot.pos) <= reach
    ]
    if not targets:
        return None
    nearest = min(
        targets,
        key=lambda robot: (distance(tower.pos, robot.pos), robot.robot_id),
    )
    return nearest.pos


def _step_toward(
    turn: Turn,
    role: Unit,
    target: Pos,
    claimed: set[Pos],
    *,
    inside_only: bool = False,
) -> Pos | None:
    for stand in _stand_cells(turn, role, target, claimed, inside_only):
        if stand == role.pos:
            return None
        step = next_step(turn, role, stand)
        if step is None or step in claimed:
            continue
        claimed.add(step)
        return step
    return None


def _stand_cells(
    turn: Turn,
    role: Unit,
    target: Pos,
    claimed: set[Pos],
    inside_only: bool = False,
) -> list[Pos]:
    station = turn.station()
    footprint = station_footprint(station.pos) if station else ()
    blocked = turn.blocked(role)
    cells = [
        p for p in _neighbours(target)
        if turn.land(p)
        and p not in blocked
        and (p == role.pos or p not in claimed)
        and (not inside_only or _footprint_distance(p, footprint) <= 1)
    ]
    cells.sort(key=lambda p: (_footprint_distance(p, footprint), p.x, p.y))
    return cells


def _footprint_distance(pos: Pos, footprint: tuple[Pos, ...]) -> int:
    if not footprint:
        return 0
    return min(distance(pos, cell) for cell in footprint)


def _neighbours(pos: Pos) -> tuple[Pos, ...]:
    return tuple(
        Pos(pos.x + dx, pos.y + dy) for dx, dy in _NEIGHBOUR_STEPS
    )
