"""M5 专项验收：多回合任务状态机（V5.1-V5.10）。"""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "CoreGeek" / "src"))

from agent.brain import _MEM, decide  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
base = json.loads((FIX / "day_news.json").read_text(encoding="utf-8"))
base["worldNews"]["officialNews"] = "今日无重大新闻"
base["worldNews"]["folkLegends"] = ""
TASK_POINT = (14, 14)  # challengerTaskPoint1


def make_round(round_no, pioneer_pos, phase_task="", last_cmd="", llm_resp="", cold_down=0):
    p = copy.deepcopy(base)
    p["roundNo"] = round_no
    for r in p["teamOur"]["roles"]:
        if r["id"] == 10011:
            r["pos"] = {"x": pioneer_pos[0], "y": pioneer_pos[1]}
    p["phaseTask"] = phase_task
    p["lastCmdResult"] = last_cmd
    p["llmResp"] = llm_resp
    p["lastSummonTreasureResult"] = 0
    p["lastRoundRoleActionResults"] = {}
    p["errors"] = []
    for pt in p["teamOur"]["playerTasks"]:
        pt["coldDownRounds"] = cold_down
        pt["isValid"] = (cold_down == 0)
        pt["timeoutRounds"] = 50
    return p


def pioneer_cmd(resp):
    return resp.role_command_map.get("10011")


def main():
    _MEM.__init__()
    # R1: pioneer@(10,12) 远离任务点 → move toward [V5.1]
    resp1 = decide(make_round(10, (10, 12)))
    c1 = pioneer_cmd(resp1)
    assert c1 and c1["action"] == "move", f"V5.1 期望 move, 实际 {c1}"
    print(f"[V5.1] pioneer 走向任务点 move ✓")

    # R2-R3: 继续接近（手动推进位置）
    decide(make_round(11, (11, 13)))
    decide(make_round(12, (12, 14)))

    # R4: pioneer@(13,14) 邻任务点 → acceptTask [V5.2]
    resp4 = decide(make_round(13, (13, 14)))
    c4 = pioneer_cmd(resp4)
    assert c4 and c4["action"] == "acceptTask", f"V5.2 期望 acceptTask, 实际 {c4}"
    print(f"[V5.2] 到任务点旁 acceptTask ✓")

    # R5: phase_task 非空 → sync 启动 active_task, dispatch executeCmd, pioneer 不动 [V5.3/5.4/5.9]
    resp5 = decide(make_round(14, (13, 14), phase_task="查询北京天气的API", cold_down=30))
    assert _MEM.active_task is not None, "V5.3 active_task 未启动"
    assert resp5.execute_cmd != "", "V5.4 executeCmd 未产出"
    c5 = pioneer_cmd(resp5)
    assert c5 is None, f"V5.9 任务期开拓者动了: {c5}"
    print(f"[V5.3] active_task 启动 ✓ | [V5.4] executeCmd={resp5.execute_cmd!r} ✓ | [V5.9] 任务期不动 ✓")

    # R6: lastCmdResult 非空 → 存入 observations; dispatch prompt [V5.5/5.6]
    resp6 = decide(make_round(15, (13, 14), phase_task="查询北京天气",
                              last_cmd="[exitCode:0]\n北京:晴", cold_down=29))
    assert _MEM.active_task and len(_MEM.active_task.observations) > 0, "V5.5 observation 未存储"
    assert resp6.prompt != "", "V5.6 prompt 未产出"
    obs = _MEM.active_task.observations[-1]
    print(f"[V5.5] lastCmdResult 存入 observations({obs[:20]!r}) ✓ | [V5.6] prompt 产出 ✓")

    # R7: llmResp 非空 → 存入 llm_observations; derive answer → submitAnswer [V5.7/5.8]
    resp7 = decide(make_round(16, (13, 14), phase_task="查询北京天气",
                              llm_resp="北京天气:晴", cold_down=28))
    assert _MEM.active_task and len(_MEM.active_task.llm_observations) > 0, "V5.7 llm_observation 未存储"
    c7 = pioneer_cmd(resp7)
    assert c7 and c7["action"] == "submitAnswer", f"V5.8 期望 submitAnswer, 实际 {c7}"
    print(f"[V5.7] llmResp 存入 llm_observations ✓ | [V5.8] submitAnswer ✓")

    # R8: phase_task 空 → sync 结束任务 [V5.x 任务结束]
    decide(make_round(17, (13, 14), phase_task="", cold_down=27))
    assert _MEM.active_task is None, "任务未结束"
    print(f"[任务结束] phase_task 空 → active_task=None ✓")

    # V5.10: 不破坏 M1-M4 全 fixture
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "replay.py")],
        capture_output=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert r.stdout and "[ALL PASS]" in r.stdout, f"V5.10 replay 未全过:\n{r.stdout[-500:]}"
    print(f"[V5.10] 全 fixture replay [ALL PASS] ✓")

    print(f"\n{'='*40}")
    print("[M5 ALL PASS]")


if __name__ == "__main__":
    main()
