from __future__ import annotations

from typing import Any

from .grid import next_step
from .memory import (
    Memory,
    TASK_ACCEPTED,
    TASK_ANSWERED,
    TASK_DONE,
    TASK_EXPLORING,
    TASK_TIMEOUT,
)
from .protocol import (
    Pos,
    Turn,
    Unit,
    accept_task_command,
    distance,
    move_command,
    submit_answer_command,
)

# 任务期最大探索轮数（避免无限探索）
_MAX_EXPLORE_TURNS = 8


def sync_task_state(turn: Turn, mem: Memory) -> None:
    """根据 phase_task 同步任务状态机（每回合开头调）。"""
    if turn.phase_task and mem.active_task is None:
        _start_task(turn, mem)
    elif not turn.phase_task and mem.active_task is not None:
        if mem.active_task.phase not in (TASK_DONE, TASK_TIMEOUT):
            mem.active_task.phase = (
                TASK_DONE if mem.active_task.last_answer else TASK_TIMEOUT
            )
        mem.active_task = None


def _start_task(turn: Turn, mem: Memory) -> None:
    target = mem.pending_task_point
    chosen = None
    for pt in turn.player_tasks:
        if target is not None and distance(pt.task_position, target) <= 1:
            chosen = pt
            break
    if chosen is None:
        for pt in turn.player_tasks:
            if pt.can_accept:
                chosen = pt
                break
    if chosen is None:
        return
    mem.start_task(
        chosen.task_type, chosen.task_position, turn.round_no,
        chosen.timeout_rounds, chosen.score_reward, chosen.gold_reward,
    )
    mem.pending_task_point = None


def plan_pioneer_action(
    turn: Turn, mem: Memory, pioneer: Unit, claimed: set[Pos]
) -> dict[str, Any] | None:
    """开拓者任务动作：任务期→submitAnswer/不动；非任务期→走向任务点+acceptTask。"""
    task = mem.active_task
    if task is not None and task.is_active():
        # B2: 任务期不移动，只提交答案
        answer = _derive_answer(turn, mem, task)
        if answer:
            task.last_answer = answer
            task.phase = TASK_ANSWERED
            return submit_answer_command(answer)
        return None  # 等待工具结果，保持不动
    # 非任务期：走向最近可接任务点
    tp = _best_task_point(turn, pioneer)
    if tp is None:
        return None
    if distance(pioneer.pos, tp) <= 1:
        mem.pending_task_point = tp
        return accept_task_command()
    step = _move_toward(turn, pioneer, tp, claimed)
    return step


def dispatch_tools(turn: Turn, mem: Memory) -> tuple[str, str]:
    """任务期工具调度：返回 (prompt, execute_cmd)。
    异步模式：本回合提交，下回合 memory.update 消费结果。"""
    task = mem.active_task
    if task is None or not task.is_active():
        return "", ""
    if task.phase == TASK_ACCEPTED:
        task.phase = TASK_EXPLORING
    if task.phase != TASK_EXPLORING:
        return "", ""
    # 探索轮数上限：避免无限消耗
    explore_turns = len(task.observations) + len(task.llm_observations)
    if explore_turns >= _MAX_EXPLORE_TURNS:
        return "", ""
    # 1. SOP 复用：同类型任务已有沉淀脚本 → 直接用
    sop = mem.sop_library.get(task.task_type)
    if sop and sop.script and mem.pending_cmd is None:
        mem.request_cmd(sop.script)
        return "", sop.script
    # 2. 沙盒探索（首次：observations 为空时探测一次）
    if mem.pending_cmd is None and not task.observations:
        cmd = _gen_explore_cmd(turn, task)
        if cmd:
            mem.request_cmd(cmd)
            return "", cmd
    # 3. LLM 探索（有沙盒观察后用 LLM 解读/生成答案）
    if mem.pending_llm is None and mem.llm_budget_remaining(in_task=True) > 0:
        prompt = _gen_explore_prompt(turn, task)
        if mem.request_llm(prompt, in_task=True):
            return prompt, ""
    return "", ""


def distill_sop(task: "TaskState", observations: list[str]) -> "SOP":
    """任务完成后蒸馏 SOP：固化探索脚本供同类型任务复用。"""
    from .memory import SOP
    script = ""
    for obs in observations:
        if "[exitCode:0]" in obs:
            # 提取成功的命令作为脚本
            lines = obs.split("\n", 1)
            if len(lines) == 2:
                script = lines[0].replace("[exitCode:0]", "").strip() or script
    return SOP(
        task_signature=task.task_type,
        steps=[],
        script=script,
        failure_modes=[],
    )


def _derive_answer(turn: Turn, mem: Memory, task: "TaskState") -> str:
    """从累积观察推导答案：优先 LLM 答案；LLM 配额耗尽时用沙盒输出兜底。"""
    if task.llm_observations:
        return task.llm_observations[-1].strip()
    if mem.llm_budget_remaining(in_task=True) <= 0 and task.observations:
        last = task.observations[-1]
        return last.split("\n", 1)[1].strip() if "\n" in last else last.strip()
    return ""


def _gen_explore_cmd(turn: Turn, task: "TaskState") -> str:
    """生成探索沙盒命令：用 echo 探测任务描述。"""
    safe = (turn.phase_task or task.task_type)[:60].replace("'", "")
    return f"echo 'explore {task.task_type}: {safe}'"


def _gen_explore_prompt(turn: Turn, task: "TaskState") -> str:
    """生成 LLM 探索 prompt。"""
    return (
        f"任务描述: {turn.phase_task}\n"
        f"已观察: {task.observations[-3:] if task.observations else '无'}\n"
        f"请分析任务并给出可执行的 shell/python 命令来获取答案。"
    )


def _best_task_point(turn: Turn, pioneer: Unit) -> Pos | None:
    candidates = [pt.task_position for pt in turn.player_tasks if pt.can_accept]
    if not candidates:
        return None
    return min(candidates, key=lambda p: distance(pioneer.pos, p))


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
