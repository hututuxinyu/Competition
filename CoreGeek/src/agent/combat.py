from __future__ import annotations

from typing import Any

from .memory import Memory
from .protocol import (
    Pos,
    Robot,
    Turn,
    Unit,
    attack_command,
    distance,
    use_command,
)
from .util import bresenham_line, cone_check

# 道具优先级：BOSS眩晕 > 范围炸弹清群
BOSS_TYPE = "bossRobot"


def act_at_tower(
    turn: Turn,
    role: Unit,
    tower: Unit,
    commands: dict[int, dict[str, Any]],
) -> None:
    """角色已在武器旁：先评估道具(眩晕BOSS/炸弹清群)，否则操控武器攻击。"""
    item_cmd = _plan_combat_item(turn, role, tower)
    if item_cmd is not None:
        commands[role.unit_id] = item_cmd
        return
    if tower.cooldown > 0:
        return
    targets = select_targets(turn, tower)
    if targets:
        commands[tower.unit_id] = attack_command(role.unit_id, targets)


def select_targets(turn: Turn, tower: Unit) -> list[Pos]:
    """按武器类型选择目标：加特林锥形多目标/电磁炮穿透/火箭溅射聚类。"""
    reach = tower.range_of_attack()
    candidates = [
        r for r in turn.robots
        if r.health > 0 and distance(tower.pos, r.pos) <= reach
    ]
    if not candidates:
        return []
    if tower.kind == "gatling":
        return _gatling_targets(candidates, tower)
    if tower.kind == "railgun":
        target = _railgun_target(candidates, tower)
        return [target] if target is not None else []
    if tower.kind == "rocket":
        return _rocket_targets(candidates, tower)
    return []


def _gatling_targets(candidates: list[Robot], tower: Unit) -> list[Pos]:
    """加特林：BOSS优先(积分高)，多目标须同 90° 锥。"""
    n = tower.max_targets()
    ranked = sorted(
        candidates,
        key=lambda r: (-r.score, distance(tower.pos, r.pos)),
    )
    selected: list[Robot] = []
    for r in ranked:
        if len(selected) >= n:
            break
        trial = [t.pos for t in selected] + [r.pos]
        if cone_check(tower.pos, trial):
            selected.append(r)
    return [t.pos for t in selected]


def _railgun_target(candidates: list[Robot], tower: Unit) -> Pos | None:
    """电磁炮：选弹道穿最多机器人的方向，取该方向最远机器人为落点。"""
    best_count = 0
    best_target: Robot | None = None
    for r in candidates:
        line = set(bresenham_line(tower.pos, r.pos))
        on_line = [c for c in candidates if c.pos in line]
        count = len(on_line)
        farthest = max(on_line, key=lambda c: distance(tower.pos, c.pos))
        if count > best_count or (
            count == best_count
            and best_target is not None
            and distance(tower.pos, farthest.pos) > distance(tower.pos, best_target.pos)
        ):
            best_count = count
            best_target = farthest
    return best_target.pos if best_target is not None else None


def _rocket_targets(candidates: list[Robot], tower: Unit) -> list[Pos]:
    """火箭：贪心选 3×3(半径1)覆盖最多机器人的落点，落点重叠伤害叠加。"""
    n = tower.max_targets()
    remaining = list(candidates)
    selected: list[Pos] = []
    while remaining and len(selected) < n:
        best_pos: Pos | None = None
        best_cover = 0
        for r in remaining:
            cover = sum(1 for c in remaining if distance(c.pos, r.pos) <= 1)
            if cover > best_cover:
                best_cover = cover
                best_pos = r.pos
        if best_pos is None:
            break
        selected.append(best_pos)
        # 移除被本次溅射覆盖的机器人
        remaining = [c for c in remaining if distance(c.pos, best_pos) > 1]
    return selected


def _plan_combat_item(
    turn: Turn, role: Unit, tower: Unit
) -> dict[str, Any] | None:
    """道具战术：BOSS在场→眩晕法宝(控5回合)；机器人集群→范围炸弹。"""
    boss = _find_boss(turn, tower)
    if boss is not None and not boss.is_dizzy and role.has_item("DizzyWeapon"):
        return use_command("DizzyWeapon", boss.pos)
    cluster = _best_cluster(turn, tower)
    if cluster is not None and role.has_item("Bomb"):
        return use_command("Bomb", cluster)
    return None


def _find_boss(turn: Turn, tower: Unit) -> Robot | None:
    reach = tower.range_of_attack()
    for r in turn.robots:
        if (
            r.role_type == BOSS_TYPE
            and r.health > 0
            and distance(tower.pos, r.pos) <= reach
        ):
            return r
    return None


def _best_cluster(turn: Turn, tower: Unit) -> Pos | None:
    """选 3×3 覆盖最多机器人的位置（炸弹范围与火箭一致）。"""
    reach = tower.range_of_attack()
    candidates = [
        r for r in turn.robots
        if r.health > 0 and distance(tower.pos, r.pos) <= reach
    ]
    if len(candidates) < 3:
        return None
    best_pos: Pos | None = None
    best_cover = 0
    for r in candidates:
        cover = sum(1 for c in candidates if distance(c.pos, r.pos) <= 1)
        if cover > best_cover:
            best_cover = cover
            best_pos = r.pos
    return best_pos if best_cover >= 3 else None
