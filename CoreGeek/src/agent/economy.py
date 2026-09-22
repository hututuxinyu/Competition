from __future__ import annotations

from typing import Any

from .grid import next_step, next_step_to_adjacent
from .memory import Memory
from .protocol import (
    ORE_TYPES,
    Pos,
    STATION,
    TOWER_TYPES,
    Turn,
    Unit,
    WALL,
    buy_command,
    distance,
    move_command,
    sell_command,
    station_footprint,
    use_command,
)

# 升级优先级表：(目标类型集合, 起始level, 券名, 价格)
# 对手分析：塔升级先于基地升级（R34-R45升塔 → R169+升基地）
# 塔升级=回满血+DPS翻倍（score2击杀+防御双赢），基地升级=HP翻倍（score3生存）
UPGRADE_PLAN = [
    (TOWER_TYPES, 1, "WeaponUpgradeVoucher1", 100),
    ((STATION,), 1, "StationUpgradeVoucher1", 100),
    (TOWER_TYPES, 2, "WeaponUpgradeVoucher2", 150),
    ((STATION,), 2, "StationUpgradeVoucher2", 150),
    ((WALL,), 1, "WallUpgradeVoucher1", 20),
    ((WALL,), 2, "WallUpgradeVoucher2", 30),
]
# 卖矿最低批量：积攒足够矿石再去卖，减少往返开销
MIN_SELL_BATCH = 5

# 券名 → (目标类型集合, 起始level)
_VOUCHER_MAP = {
    "WeaponUpgradeVoucher1": (TOWER_TYPES, 1),
    "WeaponUpgradeVoucher2": (TOWER_TYPES, 2),
    "StationUpgradeVoucher1": ((STATION,), 1),
    "StationUpgradeVoucher2": ((STATION,), 2),
    "WallUpgradeVoucher1": ((WALL,), 1),
    "WallUpgradeVoucher2": ((WALL,), 2),
}

# 价格推理：矿种词 → 矿石；事件词 → 不可采/涨价
_ORE_KEYWORDS = {"铁": "iron", "铜": "copper", "石": "stone"}
_EVENT_KEYWORDS = ("塌方", "停工", "罢工", "枯竭", "矿难", "坍塌", "渗水")


def run(turn: Turn, mem: Memory, commands: dict[int, dict[str, Any]],
        assigned: set[int], claimed: set[Pos], deadline: float) -> None:
    """白天经济调度：价格推理 + 卖矿/买券/升级。"""
    update_forecast(turn, mem)
    for worker in turn.workers():
        if worker.unit_id in assigned:
            continue
        cmd = plan_action(turn, worker, claimed)
        if cmd is not None:
            commands[worker.unit_id] = cmd
            assigned.add(worker.unit_id)


def update_forecast(turn: Turn, mem: Memory) -> None:
    """价格推理：解析官方消息的矿种+事件词，标记未来2天该矿不可采(价格涨)。"""
    news = turn.world_news.official_news
    if not news or news == "今日无重大新闻":
        return
    ore = None
    for kw, o in _ORE_KEYWORDS.items():
        if kw in news:
            ore = o
            break
    if ore is None:
        return
    if not any(k in news for k in _EVENT_KEYWORDS):
        return
    for d in range(turn.day + 1, turn.day + 3):
        mem.ore_unavailable_days.setdefault(ore, set()).add(d)


def plan_collect(
    turn: Turn, worker: Unit, mem: Memory, claimed: set[Pos]
) -> dict[str, Any] | None:
    """采集倾斜：优先采身边的矿(distance<=1)；缺石头建墙时优先采石矿；
    否则明天不可采的矿优先囤货，否则按当前价高优先，选最近矿移动过去。"""
    if worker.backpack_full:
        return None
    from .protocol import collect_command
    # 1. 优先采身边的矿（distance<=1），无论价格——避免舍近求远跑空
    for ore in ORE_TYPES:
        for pos in turn.mines(ore):
            if pos in claimed:
                continue
            if worker.pos != pos and distance(worker.pos, pos) <= 1:
                claimed.add(pos)
                return collect_command(pos)
    # 2. 否则按 priority（不可采囤货1000 > 矿石单价）+ 距离选远矿移动
    # 缺石头时提升石矿优先级（建墙需要石头），夜间墙被毁后白天优先采石重建
    # 墙少于墙位规划的一半时 → 急需石矿
    need_stone = len(turn.walls()) < 5
    candidates: list[tuple[int, str, Pos]] = []
    for ore in ORE_TYPES:
        for pos in turn.mines(ore):
            if pos in claimed:
                continue
            unavail_tomorrow = (
                ore in mem.ore_unavailable_days
                and (mem.day + 1) in mem.ore_unavailable_days[ore]
            )
            priority = 1000 if unavail_tomorrow else turn.vendor_price(ore)
            if need_stone and ore == "stone":
                priority += 50  # 建墙期石矿最高优先（0墙=基地被速灭）
            candidates.append((priority, ore, pos))
    candidates.sort(
        key=lambda x: (distance(worker.pos, x[2]) - x[0] * 0.5, x[2].x, x[2].y)
    )
    for _, ore, pos in candidates:
        step = _move_toward(turn, worker, pos, claimed)
        if step is not None:
            return step
    # 3. A*失败→贪心移动到最近矿
    return _greedy_move_to_nearest_mine(turn, worker, claimed)


def plan_action(turn: Turn, worker: Unit, claimed: set[Pos]) -> dict[str, Any] | None:
    """单个工人的经济动作（优先级：升级>卖矿>买券>移动到经济目标）。"""
    cmd = plan_upgrade(turn, worker)
    if cmd is not None:
        return cmd
    cmd = plan_sell(turn, worker)
    if cmd is not None:
        return cmd
    cmd = plan_buy(turn, worker)
    if cmd is not None:
        return cmd
    return plan_move_to_economy(turn, worker, claimed)


def plan_sell(turn: Turn, worker: Unit) -> dict[str, Any] | None:
    """工人在小贩旁且有矿 → sell 价值最高的矿石（到了就全卖）。"""
    vendor = turn.vendor_pos()
    if vendor is None or distance(worker.pos, vendor) > 1:
        return None
    best_ore: str | None = None
    best_count = 0
    best_value = 0
    for ore in ORE_TYPES:
        count = worker.item_count(ore)
        if count == 0:
            continue
        value = turn.vendor_price(ore) * count
        if value > best_value:
            best_value = value
            best_ore = ore
            best_count = count
    if best_ore is None:
        return None
    return sell_command(best_ore, best_count)


def plan_buy(turn: Turn, worker: Unit) -> dict[str, Any] | None:
    """工人在武器商店旁且金币够 → buy 优先级最高的缺券。"""
    shop = turn.weapon_shop_pos()
    if shop is None or distance(worker.pos, shop) > 1:
        return None
    for kinds, from_level, voucher, price in UPGRADE_PLAN:
        if turn.gold < price:
            continue
        if worker.has_item(voucher):
            continue
        if _has_upgrade_target(turn, kinds, from_level):
            return buy_command(voucher, 1)
    return None


def plan_upgrade(turn: Turn, worker: Unit) -> dict[str, Any] | None:
    """worker 背包含券且在可升级目标旁 → use 升级。"""
    for item in worker.backpack:
        if item not in _VOUCHER_MAP:
            continue
        target = _find_upgrade_target(turn, worker, item)
        if target is not None:
            return use_command(item, target.pos)
    return None


def plan_move_to_economy(
    turn: Turn, worker: Unit, claimed: set[Pos]
) -> dict[str, Any] | None:
    """工人在经济目标旁则原地不动；否则移动到最近经济目标。"""
    # 有券 → 走向可升级目标
    for item in worker.backpack:
        if item in _VOUCHER_MAP:
            target = _nearest_upgrade_target(turn, worker, item)
            if target is not None:
                step = _move_toward(turn, worker, target, claimed)
                if step is not None:
                    return step
                # A*失败→贪心兜底
                greedy = _greedy_move_to(turn, worker, target, claimed)
                if greedy is not None:
                    return greedy
    # 有矿 → 走向小贩（攒够批量才去）
    total_ore = sum(worker.item_count(o) for o in ORE_TYPES)
    if total_ore >= MIN_SELL_BATCH or worker.backpack_full:
        vendor = turn.vendor_pos()
        if vendor is not None:
            step = _move_toward(turn, worker, vendor, claimed)
            if step is not None:
                return step
            greedy = _greedy_move_to(turn, worker, vendor, claimed)
            if greedy is not None:
                return greedy
    # 金币够买最便宜券(20金) → 走向商店
    if turn.gold >= 20:
        shop = turn.weapon_shop_pos()
        if shop is not None:
            step = _move_toward(turn, worker, shop, claimed)
            if step is not None:
                return step
            greedy = _greedy_move_to(turn, worker, shop, claimed)
            if greedy is not None:
                return greedy
    return None


def _has_upgrade_target(turn: Turn, kinds: tuple[str, ...], from_level: int) -> bool:
    for unit in turn.ours:
        if unit.kind in kinds and unit.level == from_level and unit.health > 0:
            return True
    return False


def _find_upgrade_target(turn: Turn, worker: Unit, voucher: str) -> Unit | None:
    kinds, from_level = _VOUCHER_MAP.get(voucher, ((), 0))
    candidates = [
        u for u in turn.ours
        if u.kind in kinds and u.level == from_level and u.health > 0
    ]
    for target in candidates:
        if _is_adjacent_to(worker.pos, target):
            return target
    return None


def _nearest_upgrade_target(turn: Turn, worker: Unit, voucher: str) -> Pos | None:
    kinds, from_level = _VOUCHER_MAP.get(voucher, ((), 0))
    best: Unit | None = None
    best_dist = 10 ** 9
    for unit in turn.ours:
        if unit.kind in kinds and unit.level == from_level and unit.health > 0:
            d = _pos_distance_to_unit(worker.pos, unit)
            if d < best_dist:
                best_dist = d
                best = unit
    return best.pos if best is not None else None


def _is_adjacent_to(pos: Pos, target: Unit) -> bool:
    if target.kind == STATION:
        fp = station_footprint(target.pos)
        return min(distance(pos, c) for c in fp) <= 1
    return distance(pos, target.pos) <= 1


def _pos_distance_to_unit(pos: Pos, target: Unit) -> int:
    if target.kind == STATION:
        fp = station_footprint(target.pos)
        return min(distance(pos, c) for c in fp)
    return distance(pos, target.pos)


def _move_toward(
    turn: Turn, worker: Unit, target: Pos, claimed: set[Pos]
) -> dict[str, Any] | None:
    if distance(worker.pos, target) <= 1:
        return None
    step = next_step_to_adjacent(turn, worker, target, claimed)
    if step is None or step in claimed:
        return None
    claimed.add(step)
    return move_command(step)


_NEIGHBOUR_STEPS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


def _greedy_move_to_nearest_mine(
    turn: Turn, worker: Unit, claimed: set[Pos]
) -> dict[str, Any] | None:
    """A* 寻路失败时的贪心兜底：朝最近矿区方向走一步，防0-cmd停摆。"""
    best_dist = 10 ** 9
    target: Pos | None = None
    for ore in ORE_TYPES:
        for pos in turn.mines(ore):
            d = distance(worker.pos, pos)
            if d < best_dist:
                best_dist = d
                target = pos
    if target is None:
        return None
    return _greedy_move_to(turn, worker, target, claimed)


def _greedy_move_to(
    turn: Turn, worker: Unit, target: Pos, claimed: set[Pos]
) -> dict[str, Any] | None:
    """贪心移动：朝 target 方向走一步（不做完整A*）。"""
    blocked = turn.blocked(worker)
    dx = _sign(target.x - worker.pos.x)
    dy = _sign(target.y - worker.pos.y)
    candidates: list[Pos] = []
    if dx != 0 and dy != 0:
        candidates.append(Pos(worker.pos.x + dx, worker.pos.y + dy))
    if dx != 0:
        candidates.append(Pos(worker.pos.x + dx, worker.pos.y))
    if dy != 0:
        candidates.append(Pos(worker.pos.x, worker.pos.y + dy))
    for sdx, sdy in _NEIGHBOUR_STEPS:
        p = Pos(worker.pos.x + sdx, worker.pos.y + sdy)
        if p not in candidates:
            candidates.append(p)
    for step in candidates:
        if (step != worker.pos and turn.land(step)
                and step not in blocked and step not in claimed):
            claimed.add(step)
            return move_command(step)
    return None


def _sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0
