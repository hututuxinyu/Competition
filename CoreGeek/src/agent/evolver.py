from __future__ import annotations

import json
import re
from typing import Any

from .grid import next_step, next_step_to_adjacent
from .memory import (
    Memory,
    TASK_ACCEPTED,
    TASK_ANSWERED,
    TASK_DONE,
    TASK_EXPLORING,
    TASK_TIMEOUT,
)
from .protocol import (
    DAY_ROUNDS,
    Pos,
    ROUNDS_PER_DAY,
    Turn,
    Unit,
    accept_task_command,
    distance,
    move_command,
    submit_answer_command,
)

# 任务期最大探索轮数（避免无限消耗）
_MAX_EXPLORE_TURNS = 12

# 探索步骤常量
_STEP_FIND = 0
_STEP_CAT_TASK = 1
_STEP_ANALYZE = 2
_STEP_CAT_DOCS = 3
_STEP_CURL = 4
_STEP_ANSWER = 5
_STEP_CHECK = 6
_STEP_FIX = 7
_STEP_RECHECK = 8


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
    """开拓者任务动作：任务期→submitAnswer/不动；非任务期→走向任务点+acceptTask。
    夜晚前(白天最后5回合)主动中断未完成任务回武器防御。"""
    task = mem.active_task
    if task is not None and task.is_active():
        round_in_day = (turn.round_no - 1) % ROUNDS_PER_DAY
        # 夜晚前中断：白天最后5回合且任务未提交答案 → 结束任务回武器
        if round_in_day >= DAY_ROUNDS - 5 and not task.last_answer:
            task.phase = TASK_TIMEOUT
            mem.active_task = None
            return None  # 让 brain 走 _pioneer_to_tower 回武器防御
        # 已提交过答案 → 不重复提交(等任务结束/超时)，避免卡死循环
        if task.last_answer:
            return None
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
    异步：本回合提交，下回合 memory.update 消费结果。"""
    task = mem.active_task
    if task is None or not task.is_active():
        return "", ""
    if task.phase == TASK_ACCEPTED:
        task.phase = TASK_EXPLORING
    if task.phase != TASK_EXPLORING:
        return "", ""
    explore_turns = len(task.observations) + len(task.llm_observations)
    if explore_turns >= _MAX_EXPLORE_TURNS:
        return "", ""
    # 1. SOP 复用：同类型任务已有沉淀脚本 → 直接用
    sop = mem.sop_library.get(task.task_type)
    if sop and sop.script and mem.pending_cmd is None:
        mem.request_cmd(sop.script)
        return "", sop.script
    # 2. 沙盒探索（分步引擎）
    if mem.pending_cmd is None:
        cmd = _gen_explore_cmd(turn, task)
        if cmd:
            mem.request_cmd(cmd)
            return "", cmd
    # 3. API 类 curl 完成后：用 LLM 从数据+任务要求生成答案
    if task.task_kind == "api" and task.explore_step >= _STEP_ANSWER:
        if mem.pending_llm is None and mem.llm_budget_remaining(in_task=True) > 0:
            prompt = _gen_answer_prompt(task)
            if mem.request_llm(prompt, in_task=True):
                return prompt, ""
    # 4. 通用 LLM 兜底（未知任务类型）
    if mem.pending_llm is None and mem.llm_budget_remaining(in_task=True) > 0:
        prompt = _gen_explore_prompt(turn, task)
        if mem.request_llm(prompt, in_task=True):
            return prompt, ""
    return "", ""


def _gen_explore_cmd(turn: Turn, task: "TaskState") -> str | None:
    """分步探索引擎：根据 explore_step + 上回合 observation 生成下一条命令。"""
    obs = task.observations
    step = task.explore_step

    if step == _STEP_FIND:
        task.explore_step = _STEP_CAT_TASK
        fname = _extract_filename(turn.phase_task)
        return f"find . /home /tmp /data /opt /root -maxdepth 4 -name '{fname}' 2>/dev/null | head -5"

    if step == _STEP_CAT_TASK:
        path = _extract_path(obs[-1] if obs else "")
        if not path:
            return None
        task.task_file_path = path
        task.work_dir = path.rsplit("/", 1)[0] if "/" in path else "."
        task.explore_step = _STEP_ANALYZE
        return f"cat '{path}' 2>/dev/null | head -200"

    if step == _STEP_ANALYZE:
        content = obs[-1] if obs else ""
        if _is_engineering_task(content):
            task.task_kind = "engineering"
            task.explore_step = _STEP_CHECK
        else:
            task.task_kind = "api"
            task.explore_step = _STEP_CAT_DOCS
        return _gen_explore_cmd(turn, task)  # 递归到下一步

    if step == _STEP_CAT_DOCS:
        task.explore_step = _STEP_CURL
        return f"cat '{task.work_dir}/API_DOCS.md' 2>/dev/null | head -200"

    if step == _STEP_CURL:
        docs = obs[-1] if obs else ""
        cmd = _build_curl_cmd(docs, task)
        task.explore_step = _STEP_ANSWER
        return cmd

    if step == _STEP_CHECK:
        task.explore_step = _STEP_FIX
        return (
            f"cd '{task.work_dir}' && cat spec.md 2>/dev/null; "
            f"echo '---CHECK---'; bash check 2>&1 | head -50"
        )

    if step == _STEP_FIX:
        check_out = obs[-1] if obs else ""
        fix = _build_fix_cmd(check_out, task)
        task.explore_step = _STEP_RECHECK
        return fix

    if step == _STEP_RECHECK:
        # check 输出由 _derive_answer 提取 TOKEN
        return None

    return None


def _derive_answer(turn: Turn, mem: Memory, task: "TaskState") -> str:
    """从累积观察推导答案：优先 LLM；工程类从 check 提取 TOKEN。"""
    if task.llm_observations:
        return task.llm_observations[-1].strip()
    # 工程类：从 check 输出提取 TOKEN（仅字母数字，避免反引号等占位符）
    if task.task_kind == "engineering":
        for obs in reversed(task.observations):
            m = re.search(r"TOKEN:\s*([A-Za-z0-9]+)", obs)
            if m:
                return json.dumps({"token": m.group(1)})
    # 兜底：LLM 配额耗尽时用最后沙盒输出
    if mem.llm_budget_remaining(in_task=True) <= 0 and task.observations:
        last = task.observations[-1]
        return last.split("\n", 1)[1].strip() if "\n" in last else last.strip()
    return ""


def distill_sop(task: "TaskState", observations: list[str]) -> "SOP":
    """任务完成后蒸馏 SOP：固化成功的探索脚本供同类型任务复用。"""
    from .memory import SOP
    # 取第一条成功的命令作为脚本模板（find/cat/curl 等）
    script = ""
    for obs in observations:
        if "[exitCode:0]" in obs and "\n" in obs:
            script = obs.split("\n", 1)[0].replace("[exitCode:0]", "").strip()
            if script:
                break
    return SOP(
        task_signature=task.task_type,
        steps=[],
        script=script,
        failure_modes=[],
    )


def _extract_filename(phase_task: str) -> str:
    """从 phase_task 提取任务文件名，如 '请阅读task_1_beijing.md...' → 'task_1_beijing.md'。"""
    m = re.search(r"(task_[\w-]+\.md)", phase_task or "")
    return m.group(1) if m else "task_1.md"


def _extract_path(find_output: str) -> str:
    """从 find 输出提取第一个有效路径。"""
    for line in (find_output or "").split("\n"):
        line = line.strip()
        if line and "[exitCode" not in line and "/" in line and not line.startswith("find"):
            return line
    return ""


def _is_engineering_task(content: str) -> bool:
    """判断是否工程修复类（含 ./check / spec.md / TOKEN / 修复）。
    注意：不能只用'check'，API文档常含'check'字样会误判。"""
    return any(k in (content or "") for k in ("./check", "spec.md", "TOKEN:", "修复"))


def _build_curl_cmd(docs: str, task: "TaskState") -> str:
    """从 API_DOCS 提取 base_url/key/endpoint，拼 curl 命令。"""
    base = "http://localhost:8899"
    key = ""
    endpoint = "/api/v1/heritage/search"
    m = re.search(r"(https?://[\w:.]+)", docs or "")
    if m:
        base = m.group(1).rstrip("/")
    m = re.search(r"API-Key[`:>\s]+([a-zA-Z0-9-]+)", docs or "")
    if m:
        key = m.group(1)
    m = re.search(r"(/api/[\w/]+)", docs or "")
    if m:
        endpoint = m.group(1)
    # 查询参数：从任务文件提取 city 等
    city = "北京"
    task_content = task.observations[1] if len(task.observations) >= 2 else ""
    mc = re.search(r"city[=：\s]+([^\s,}]+)", task_content)
    if mc:
        city = mc.group(1)
    header = ""
    if key:
        # 双 header 保险(部分API用 Authorization)
        header = f'-H "X-API-Key: {key}" -H "Authorization: Bearer {key}"'
    return f'curl -s {header} "{base}{endpoint}?city={city}" 2>/dev/null | head -200'


def _build_fix_cmd(check_out: str, task: "TaskState") -> str | None:
    """从 check 的 [FAIL] 行解析并生成修复命令。"""
    fixes: list[str] = []
    for line in (check_out or "").split("\n"):
        if "FAIL" not in line:
            continue
        m = re.search(r"DIR:\s*(\S+)\s+needs\s+(\S+)", line)
        if m:
            d, perm = m.group(1), m.group(2)
            fixes.append(f"mkdir -p '{task.work_dir}/{d}' && chmod {perm} '{task.work_dir}/{d}'")
        m = re.search(r"LINE:\s*(\S+):(\d+)\s+expected='(.+?)'\s+actual=", line)
        if m:
            f, ln, val = m.group(1), m.group(2), m.group(3)
            fixes.append(f"sed -i '{ln}s#.*#{val}#' '{task.work_dir}/{f}'")
    if fixes:
        return " && ".join(fixes) + f" && cd '{task.work_dir}' && bash check 2>&1 | head -50"
    return None


def _gen_answer_prompt(task: "TaskState") -> str:
    """API 类：让 LLM 从 curl 数据 + 任务要求生成答案 JSON。"""
    task_content = task.observations[1] if len(task.observations) >= 2 else ""
    curl_data = task.observations[-1] if task.observations else ""
    return (
        f"任务要求:\n{task_content[:1500]}\n\n"
        f"API 返回数据:\n{curl_data[:1500]}\n\n"
        f"请根据任务要求的提交格式，从数据中提取答案字段。"
        f"只返回 JSON 答案，不要解释。"
    )


def _gen_explore_prompt(turn: Turn, task: "TaskState") -> str:
    """通用 LLM 探索 prompt（兜底）。"""
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
    step = next_step_to_adjacent(turn, role, target, claimed)
    if step is None or step in claimed:
        return None
    claimed.add(step)
    return move_command(step)
