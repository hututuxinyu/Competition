from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .protocol import (
    ERR_LLM_LIMIT,
    Pos,
    SUMMON_SUCCESS,
    SUMMON_TREASURE_EMPTY,
    Turn,
)


# —— 任务用品与 LLM/沙盒的异步配对状态 ——
TASK_IDLE = "idle"
TASK_ACCEPTED = "accepted"
TASK_EXPLORING = "exploring"
TASK_ANSWERED = "answered"
TASK_DONE = "done"
TASK_TIMEOUT = "timeout"


@dataclass
class TaskState:
    task_type: str
    task_position: Pos
    accept_round: int
    timeout_rounds: int
    score_reward: int
    gold_reward: int
    phase: str = TASK_ACCEPTED
    observations: list[str] = field(default_factory=list)
    llm_observations: list[str] = field(default_factory=list)
    current_sop: "SOP | None" = None
    pending_query: str = ""
    pending_query_type: str = ""  # "llm" / "cmd" / ""
    last_answer: str = ""
    best_pass_rate: float = 0.0
    # 沙盒探索引擎状态
    explore_step: int = 0          # 探索进度
    task_file_path: str = ""       # find 到的任务文件路径
    work_dir: str = ""             # 任务工作目录
    task_kind: str = ""            # "api" / "engineering"

    def is_active(self) -> bool:
        return self.phase not in (TASK_DONE, TASK_TIMEOUT)

    def rounds_since_accept(self, round_no: int) -> int:
        return round_no - self.accept_round

    def is_expired(self, round_no: int) -> bool:
        return self.rounds_since_accept(round_no) >= self.timeout_rounds


@dataclass
class SOP:
    task_signature: str
    steps: list[str] = field(default_factory=list)
    script: str = ""
    failure_modes: list[str] = field(default_factory=list)
    api_template: dict[str, Any] = field(default_factory=dict)


@dataclass
class NewsRecord:
    day: int
    round_no: int
    official_news: str
    folk_legends: str


@dataclass
class PricePoint:
    day: int
    round_no: int
    price: int


class Memory:
    """跨回合记忆容器。ThreadingHTTPServer 多线程下用锁保护更新。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # —— 基础 ——
        self.round_no: int = 0
        self.day: int = 1
        self.is_day: bool = True
        self.is_new_day: bool = True
        self.team_type: str = ""

        # —— 价格推理 ——
        self.news_history: list[NewsRecord] = []
        self.price_history: dict[str, list[PricePoint]] = {}
        self.price_forecast: dict[str, dict[int, int]] = {}  # ore -> {day -> 预测价}
        self.ore_unavailable_days: dict[str, set[int]] = {}  # ore -> 不可采的天集合

        # —— 宝藏 ——
        self.folk_legend_log: list[str] = []
        self.treasure_hypothesis: dict[str, Any] = {}
        self.treasure_opened: bool = False

        # —— 自进化任务 ——
        self.active_task: TaskState | None = None
        self.sop_library: dict[str, SOP] = {}
        self.llm_budget_used: int = 0
        self.pending_llm: str | None = None
        self.pending_cmd: str | None = None
        self.pending_task_point: Pos | None = None

        # —— 战斗 ——
        self.robot_trajectory: dict[int, list[Pos]] = {}

        # —— 对抗 ——
        self.summon_used_today: int = 0

        # —— 上回合动作合法性（用于自纠错）——
        self.last_action_results: dict[int, bool] = {}

    def update(self, turn: Turn) -> None:
        """每回合开始时增量更新记忆。必须在 brain 决策前调用。"""
        with self._lock:
            prev_day = self.day
            self.round_no = turn.round_no
            self.day = turn.day
            self.is_day = turn.is_day
            self.is_new_day = turn.is_new_day
            self.team_type = turn.team_type

            # 新游戏日重置 LLM 配额与召唤令计数
            if turn.is_new_day or self.day != prev_day:
                self.llm_budget_used = 0
                self.summon_used_today = 0

            # LLM 额度超限(errorCode=5)→标记配额耗尽，降级纯沙盒
            if turn.has_error(ERR_LLM_LIMIT):
                self.llm_budget_used = 3

            # —— 价格推理 ——
            if turn.world_news.official_news or turn.world_news.folk_legends:
                self.news_history.append(NewsRecord(
                    day=turn.day,
                    round_no=turn.round_no,
                    official_news=turn.world_news.official_news,
                    folk_legends=turn.world_news.folk_legends,
                ))
            if turn.world_news.folk_legends:
                self.folk_legend_log.append(turn.world_news.folk_legends)

            # 矿石价格历史
            for ore in ("stone", "iron", "copper"):
                price = turn.vendor_price(ore)
                if price > 0:
                    self.price_history.setdefault(ore, []).append(PricePoint(
                        day=turn.day, round_no=turn.round_no, price=price,
                    ))

            # —— 宝藏反馈 ——
            if turn.last_summon_result == SUMMON_SUCCESS:
                self.treasure_opened = True
            elif turn.last_summon_result == SUMMON_TREASURE_EMPTY:
                self.treasure_opened = True

            # —— 自进化任务异步配对 ——
            # 消费上回合的 LLM/沙盒结果
            if self.pending_llm is not None and turn.llm_resp:
                if self.active_task is not None:
                    self.active_task.llm_observations.append(turn.llm_resp)
                self.pending_llm = None
            elif self.pending_llm is not None and not turn.llm_resp:
                # LLM 未返回（可能额度超限），清空待处理避免错配
                self.pending_llm = None

            if self.pending_cmd is not None and turn.last_cmd_result:
                if self.active_task is not None:
                    self.active_task.observations.append(turn.last_cmd_result)
                self.pending_cmd = None
            elif self.pending_cmd is not None and not turn.last_cmd_result:
                self.pending_cmd = None

            # 任务超时检查
            if self.active_task is not None:
                if self.active_task.is_expired(turn.round_no):
                    self.active_task.phase = TASK_TIMEOUT
                    self.active_task = None

            # —— 战斗轨迹 ——
            for robot in turn.robots:
                traj = self.robot_trajectory.setdefault(robot.robot_id, [])
                traj.append(robot.pos)
                # 只保留最近 5 步避免内存膨胀
                if len(traj) > 5:
                    traj.pop(0)
            # 清除已消失的机器人轨迹
            alive_ids = {robot.robot_id for robot in turn.robots}
            stale = [rid for rid in self.robot_trajectory if rid not in alive_ids]
            for rid in stale:
                del self.robot_trajectory[rid]

            # —— 上回合动作合法性 ——
            self.last_action_results = dict(turn.last_action_results)

    # —— LLM 配额管理 ——
    def llm_budget_remaining(self, in_task: bool = False) -> int:
        """任务期间 LLM 不计限；非任务期每游戏日 3 次。"""
        if in_task and self.active_task is not None and self.active_task.is_active():
            return 999
        return max(0, 3 - self.llm_budget_used)

    def consume_llm(self, in_task: bool = False) -> None:
        if not (in_task and self.active_task is not None and self.active_task.is_active()):
            self.llm_budget_used += 1

    def request_llm(self, prompt: str, in_task: bool = False) -> bool:
        """登记一次 LLM 请求，返回是否允许。"""
        if self.llm_budget_remaining(in_task) <= 0:
            return False
        self.consume_llm(in_task)
        self.pending_llm = prompt
        return True

    def request_cmd(self, cmd: str) -> None:
        """登记一次沙盒命令请求。"""
        self.pending_cmd = cmd

    # —— 任务管理 ——
    def start_task(self, task_type: str, position: Pos, round_no: int,
                   timeout: int, score: int, gold: int) -> None:
        self.active_task = TaskState(
            task_type=task_type,
            task_position=position,
            accept_round=round_no,
            timeout_rounds=timeout,
            score_reward=score,
            gold_reward=gold,
        )

    def finish_task(self) -> None:
        if self.active_task is not None:
            self.active_task.phase = TASK_DONE
            self.active_task = None
        self.pending_llm = None
        self.pending_cmd = None

    def is_pioneer_locked(self) -> bool:
        """B2 修正：任务期间开拓者固定在任务点，不能移动。"""
        return self.active_task is not None and self.active_task.is_active()

    # —— 召唤令管理 ——
    def can_summon(self, count: int = 1) -> bool:
        return self.summon_used_today + count <= 10

    def record_summon(self, count: int = 1) -> None:
        self.summon_used_today += count

    # —— 价格查询 ——
    def current_price(self, ore: str) -> int:
        history = self.price_history.get(ore)
        return history[-1].price if history else 0

    def is_ore_available(self, ore: str, day: int | None = None) -> bool:
        target_day = day if day is not None else self.day
        return target_day not in self.ore_unavailable_days.get(ore, set())

    # —— 机器人轨迹预测 ——
    def predict_robot_pos(self, robot_id: int) -> Pos | None:
        traj = self.robot_trajectory.get(robot_id)
        if not traj or len(traj) < 2:
            return None
        last = traj[-1]
        prev = traj[-2]
        # 简单线性外推一步（切比雪夫方向）
        dx = _sign(last.x - prev.x)
        dy = _sign(last.y - prev.y)
        predicted = Pos(last.x + dx, last.y + dy)
        return predicted


def _sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0
