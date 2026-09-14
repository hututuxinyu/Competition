"""M8 专项验收：边界 case + 回归 + HTTP E2E。"""
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
from agent.protocol import Turn  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def v81_dead_unit():
    """角色死亡(health=0)→不产生命令。"""
    _MEM.__init__()
    p = json.loads((FIX / "night_attack.json").read_text(encoding="utf-8"))
    # 杀死 worker1 10010
    for r in p["teamOur"]["roles"]:
        if r["id"] == 10010:
            r["health"] = 0
    resp = decide(p)
    assert "10010" not in resp.role_command_map, "V8.1 死亡角色仍产生命令"
    # gatling 应由其他存活角色操控或不攻击（10010 死亡）
    print(f"[V8.1] 死亡角色(10010)不产生命令 ✓")


def v82_llm_limit():
    """LLM 超限(errorCode=5)→dispatch_llm 降级不产出 prompt。"""
    _MEM.__init__()
    p = json.loads((FIX / "day_news.json").read_text(encoding="utf-8"))
    p["worldNews"]["folkLegends"] = "传闻宝藏"
    p["errors"] = [{"errorCode": 5, "description": "LLM额度超限"}]
    resp = decide(p)
    assert resp.prompt == "", f"V8.2 LLM超限仍产出 prompt: {resp.prompt!r}"
    assert _MEM.llm_budget_remaining(in_task=False) == 0, "V8.2 配额未标记耗尽"
    print(f"[V8.2] LLM超限(errorCode=5)→降级不调 LLM ✓")


def v83_mine_disappear():
    """矿区消失→采集切换其他矿。"""
    _MEM.__init__()
    p = json.loads((FIX / "day_news.json").read_text(encoding="utf-8"))
    p["worldNews"]["officialNews"] = "今日无重大新闻"
    # 移除所有 stone 矿区
    p["mapInfo"]["zones"] = [z for z in p["mapInfo"]["zones"] if z["neutralType"] != "stone"]
    turn = Turn.load(p)
    assert len(turn.stone_mines()) == 0, "V8.3 stone 矿未移除"
    # worker1@(8,27) 旁有 iron 矿(8,28)，3塔已建无建塔任务→应采 iron
    resp = decide(p)
    c = resp.role_command_map.get("10010")
    assert c and c["action"] == "collect", f"V8.3 未采集: {c}"
    assert c["targetPos"][0] == {"x": 8, "y": 28}, f"V8.3 未切换到 iron: {c}"
    print(f"[V8.3] stone 矿消失→切换采 iron(8,28) ✓")


def v84_dizzy_robot():
    """机器人眩晕(dizzy)仍可被攻击。"""
    _MEM.__init__()
    p = json.loads((FIX / "night_attack.json").read_text(encoding="utf-8"))
    # 让 BOSS 眩晕
    for r in p["robot"]["roles"]:
        if r["roleType"] == "bossRobot":
            r["abnormalState"] = "dizzy"
    resp = decide(p)
    gatling_cmd = resp.role_command_map.get("10020")
    assert gatling_cmd and gatling_cmd["action"] == "attack", "V8.4 gatling 未攻击眩晕 BOSS"
    assert gatling_cmd["targetPos"][0] == {"x": 11, "y": 21}, "V8.4 未攻击 BOSS"
    print(f"[V8.4] 眩晕 BOSS 仍被攻击 ✓")


def v85_regression():
    """M3-M7 全 validate 回归通过。"""
    scripts = ["validate_m3.py", "validate_m4.py", "validate_m5.py",
               "validate_m6.py", "validate_m7.py"]
    for s in scripts:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / s)],
            capture_output=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        tag = s.replace("validate_m", "").replace(".py", "")
        assert r.stdout and f"[M{tag} ALL PASS]" in r.stdout, \
            f"V8.5 {s} 未通过:\n{r.stdout[-400:]}\n{r.stderr[-400:]}"
    print(f"[V8.5] M3-M7 全 validate 回归通过 ✓")


def v86_http_e2e():
    """最终 HTTP E2E：白天+夜晚场景。"""
    import threading
    from http.server import ThreadingHTTPServer
    sys.path.insert(0, str(ROOT / "CoreGeek" / "src"))
    from agent.server import Handler
    server = ThreadingHTTPServer(("127.0.0.1", 9880), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    import time
    time.sleep(1)
    try:
        import urllib.request
        for name in ("day_news", "night_attack"):
            data = (FIX / f"{name}.json").read_bytes()
            req = urllib.request.Request(
                "http://127.0.0.1:9880/", data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                assert resp.status == 200, f"V8.6 {name} HTTP {resp.status}"
                assert "roleCommandMap" in body and "prompt" in body and "executeCmd" in body
                print(f"[V8.6] {name} HTTP 200, cmds={len(body['roleCommandMap'])} ✓")
    finally:
        server.shutdown()
    print(f"[V8.6] 最终 HTTP E2E 白天+夜晚通过 ✓")


def main():
    for fn in (v81_dead_unit, v82_llm_limit, v83_mine_disappear,
               v84_dizzy_robot, v85_regression, v86_http_e2e):
        fn()
    print(f"\n{'='*40}")
    print("[M8 ALL PASS]")


if __name__ == "__main__":
    main()
