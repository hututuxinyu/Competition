from __future__ import annotations

import json
import re
from typing import Any

from .grid import next_step
from .memory import Memory
from .protocol import (
    Pos,
    TASK_ITEMS,
    Turn,
    Unit,
    buy_command,
    distance,
    move_command,
    summon_treasure_command,
)

_SUMMON_WRONG_ITEM = 3


def plan_pioneer_treasure(
    turn: Turn, mem: Memory, pioneer: Unit, claimed: set[Pos]
) -> dict[str, Any] | None:
    """开拓者宝藏动作（非任务期）：买用品→走到地点→summonTreasure。"""
    if mem.treasure_opened:
        return None
    # 消费上回合 LLM 结果（非任务期）
    if turn.llm_resp and mem.active_task is None:
        _parse_hypothesis(turn.llm_resp, mem)
    # 召唤失败(物品错)→清假设重推断
    if turn.last_summon_result == _SUMMON_WRONG_ITEM:
        mem.treasure_hypothesis = {}
    hyp = mem.treasure_hypothesis
    if not hyp or "items" not in hyp or "pos" not in hyp:
        return None
    needed: list[str] = list(hyp["items"])
    target = _pos_from(hyp["pos"])
    if target is None:
        return None
    have = [i for i in needed if pioneer.has_item(i)]
    missing = [i for i in needed if i not in have]
    # 1. 缺用品→在商店旁买；否则走向商店
    if missing:
        shop = turn.weapon_shop_pos()
        if shop is not None and distance(pioneer.pos, shop) <= 1:
            name = missing[0]
            if turn.gold >= turn.weapon_price(name):
                return buy_command(name, 1)
            return None  # 金币不足
        if shop is not None:
            return _move_toward(turn, pioneer, shop, claimed)
        return None
    # 2. 用品齐→走到地点→summonTreasure
    if distance(pioneer.pos, target) <= 1:
        return summon_treasure_command(target, needed)
    return _move_toward(turn, pioneer, target, claimed)


def dispatch_llm(turn: Turn, mem: Memory) -> str:
    """非任务期：若需推断宝藏且 LLM 配额够→产出 prompt。"""
    if mem.treasure_opened:
        return ""
    if mem.treasure_hypothesis:
        return ""
    if not mem.folk_legend_log:
        return ""
    if mem.pending_llm is not None:
        return ""
    if mem.llm_budget_remaining(in_task=False) <= 0:
        return ""
    prompt = _gen_prompt(turn, mem)
    if mem.request_llm(prompt, in_task=False):
        return prompt
    return ""


def _parse_hypothesis(resp: str, mem: Memory) -> None:
    """从 LLM 响应提取 JSON 假设 {pos, items, time}。"""
    try:
        m = re.search(r"\{.*\}", resp, re.S)
        if not m:
            return
        data = json.loads(m.group())
        if isinstance(data, dict) and "pos" in data and "items" in data:
            mem.treasure_hypothesis = data
    except (json.JSONDecodeError, ValueError):
        pass


def _pos_from(raw: Any) -> Pos | None:
    try:
        return Pos(int(raw["x"]), int(raw["y"]))
    except (TypeError, KeyError, ValueError):
        return None


def _gen_prompt(turn: Turn, mem: Memory) -> str:
    legends = "\n".join(f"DAY{i+1}: {l}" for i, l in enumerate(mem.folk_legend_log[-5:]))
    items = ", ".join(TASK_ITEMS)
    return (
        f"民间传闻累积:\n{legends}\n\n"
        f"已知祭坛机制：献祭特定任务用品组合可在特定地点特定时间开启宝藏。\n"
        f"可选任务用品: [{items}]\n"
        f"请推断宝藏的 地点(坐标pos)、献祭物品组合(items)、开启时间(time)。\n"
        f"只返回JSON: {{\"pos\":{{\"x\":N,\"y\":N}},\"items\":[\"...\"],\"time\":\"DAY N\"}}"
    )


def _move_toward(
    turn: Turn, role: Unit, target: Pos, claimed: set[Pos]
) -> dict[str, Any] | None:
    if distance(role.pos, target) <= 1:
        return None
    step = next_step(turn, role, target)
    if step is None or step in claimed:
        return None
    claimed.add(step)
    return move_command(step)
