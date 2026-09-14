from __future__ import annotations

from typing import Any

from .memory import Memory
from .protocol import Turn, Unit, buy_command, distance, use_command

# 召唤令（贵→便宜），购买时反向迭代优先便宜以最大化数量
SUMMON_ORDERS = (
    ("BossRobotSummonOrder", 200),
    ("LargeRobotSummonOrder", 100),
    ("MiddleRobotSummonOrder", 30),
    ("SmallRobotSummonOrder", 20),
)
DAILY_SUMMON_LIMIT = 10
GOLD_RESERVE = 50  # 保升级预算下限


def plan_summon(
    turn: Turn, mem: Memory, worker: Unit
) -> dict[str, Any] | None:
    """召唤令骚扰：已有→使用；在商店旁+金币够→买（优先便宜最大化数量）。"""
    budget = DAILY_SUMMON_LIMIT - mem.summon_used_today
    if budget <= 0:
        return None
    # 1. 已有召唤令 → 使用（无 targetPos，作用于对方下个夜晚）
    for name, _ in SUMMON_ORDERS:
        if worker.has_item(name):
            mem.record_summon(1)
            return use_command(name)
    # 2. 在商店旁 → 买最便宜且买得起的（留 GOLD_RESERVE 保升级）
    shop = turn.weapon_shop_pos()
    if shop is None or distance(worker.pos, shop) > 1:
        return None
    for name, price in reversed(SUMMON_ORDERS):
        if turn.gold - price >= GOLD_RESERVE and not worker.has_item(name):
            return buy_command(name, 1)
    return None
