"""M3 专项验收：V3.1-V3.8 夜间战斗。"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "CoreGeek" / "src"))

from agent.brain import decide  # noqa: E402
from agent.protocol import Turn  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def run_fixture(name):
    payload = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    turn = Turn.load(payload)
    resp = decide(payload)
    return turn, resp


def v31_attack():
    turn, resp = run_fixture("night_attack")
    attacks = [c for c in resp.role_command_map.values() if c["action"] == "attack"]
    assert len(attacks) >= 3, f"V3.1 期望≥3 attack, 实际 {len(attacks)}"
    print(f"[V3.1] night_attack 产出 {len(attacks)} 个 attack 命令 ✓")


def v32_boss_priority():
    turn, resp = run_fixture("night_attack")
    # gatling(10020) 应攻击 BOSS@(11,21)
    gatling_cmd = resp.role_command_map.get("10020")
    assert gatling_cmd and gatling_cmd["action"] == "attack", "V3.2 gatling 未攻击"
    targets = gatling_cmd["targetPos"]
    boss_pos = {"x": 11, "y": 21}
    assert any(t == boss_pos for t in targets), f"V3.2 gatling 未优先 BOSS, 实际 {targets}"
    print(f"[V3.2] gatling 攻击 BOSS@(11,21) ✓")


def v33_gatling_cone():
    turn, resp = run_fixture("night_gatling")
    cmd = resp.role_command_map.get("10020")
    assert cmd and cmd["action"] == "attack", "V3.3 gatling 未攻击"
    assert len(cmd["targetPos"]) == 2, f"V3.3 期望2目标, 实际 {len(cmd['targetPos'])}"
    print(f"[V3.3] gatling L2 多目标锥形: {cmd['targetPos']} ✓")


def v34_railgun_pierce():
    turn, resp = run_fixture("night_railgun")
    cmd = resp.role_command_map.get("10030")
    assert cmd and cmd["action"] == "attack", "V3.4 railgun 未攻击"
    target = cmd["targetPos"][0]
    # 共线 (12,25)(14,25)(16,25), 应选最远 (16,25)
    assert target == {"x": 16, "y": 25}, f"V3.4 期望最远(16,25), 实际 {target}"
    print(f"[V3.4] railgun 穿透选最远共线目标 (16,25) ✓")


def v35_rocket_splash():
    turn, resp = run_fixture("night_rocket")
    cmd = resp.role_command_map.get("10040")
    assert cmd and cmd["action"] == "attack", "V3.5 rocket 未攻击"
    target = cmd["targetPos"][0]
    # 聚类 (15,25)(16,25)(15,26), 中心 (15,25) 覆盖3
    assert target == {"x": 15, "y": 25}, f"V3.5 期望聚类中心(15,25), 实际 {target}"
    print(f"[V3.5] rocket 溅射选聚类中心 (15,25) ✓")


def v36_items():
    turn, resp = run_fixture("night_items")
    worker1_cmd = resp.role_command_map.get("10010")
    assert worker1_cmd and worker1_cmd["action"] == "use", "V3.6 未用道具"
    assert worker1_cmd["name"] == "DizzyWeapon", "V3.6 未用眩晕法宝"
    assert worker1_cmd["targetPos"][0] == {"x": 11, "y": 24}, "V3.6 未指向 BOSS"
    print(f"[V3.6] use DizzyWeapon 眩晕 BOSS@(11,24) ✓")


def v37_collision():
    turn, resp = run_fixture("night_move")
    moves = [
        c["targetPos"][0] for c in resp.role_command_map.values()
        if c["action"] == "move"
    ]
    # 无两个角色目标同一格
    seen = set()
    for m in moves:
        key = (m["x"], m["y"])
        assert key not in seen, f"V3.7 碰撞: 两角色目标 {key}"
        seen.add(key)
    print(f"[V3.7] night_move {len(moves)} 个 move 目标互不冲突 ✓")


def v38_all_pass():
    import subprocess
    import os
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "replay.py")],
        capture_output=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert r.stdout and "[ALL PASS]" in r.stdout, f"V3.8 replay 未全过:\n{r.stdout}\n{r.stderr}"
    print("[V3.8] 全 fixture replay [ALL PASS] ✓")


def main():
    for fn in (v31_attack, v32_boss_priority, v33_gatling_cone, v34_railgun_pierce,
               v35_rocket_splash, v36_items, v37_collision, v38_all_pass):
        fn()
    print(f"\n{'='*40}")
    print("[M3 ALL PASS]")


if __name__ == "__main__":
    main()
