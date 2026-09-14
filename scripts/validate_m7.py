"""M7 专项验收：V7.1-V7.5 对抗压制。"""
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


def run(name, reset=True, summon_used=0):
    if reset:
        _MEM.__init__()
    if summon_used:
        _MEM.summon_used_today = summon_used
    payload = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    return decide(payload)


def worker_cmd(resp, wid=10010):
    return resp.role_command_map.get(str(wid))


def v71_buy():
    resp = run("day_summon_buy")
    cmd = worker_cmd(resp)
    assert cmd and cmd["action"] == "buy", f"V7.1 期望 buy, 实际 {cmd}"
    assert "SummonOrder" in cmd["name"], f"V7.1 非召唤令: {cmd['name']}"
    print(f"[V7.1] 商店旁买召唤令 {cmd['name']} ✓")


def v72_use():
    resp = run("day_summon_use")
    cmd = worker_cmd(resp)
    assert cmd and cmd["action"] == "use", f"V7.2 期望 use, 实际 {cmd}"
    assert "SummonOrder" in cmd["name"], f"V7.2 非召唤令: {cmd['name']}"
    print(f"[V7.2] 使用召唤令 {cmd['name']} ✓")


def v73_limit():
    # 已用10张→不应再买/用召唤令
    resp = run("day_summon_limit", summon_used=10)
    cmd = worker_cmd(resp)
    is_summon = (
        cmd and cmd.get("action") in ("buy", "use")
        and "SummonOrder" in cmd.get("name", "")
    )
    assert not is_summon, f"V7.3 超限仍召唤: {cmd}"
    assert _MEM.summon_used_today == 10, f"V7.3 召唤计数变化: {_MEM.summon_used_today}"
    print(f"[V7.3] 每日10张上限生效(已用10→不再召唤) ✓")


def v74_budget():
    # gold60, 买小令后余40<50(保预算)→不买召唤令
    resp = run("day_summon_budget")
    cmd = worker_cmd(resp)
    is_summon_buy = (
        cmd and cmd.get("action") == "buy" and "SummonOrder" in cmd.get("name", "")
    )
    assert not is_summon_buy, f"V7.4 金币不足保预算仍买: {cmd}"
    print(f"[V7.4] 金币不足保升级预算(留50)→不买召唤令 ✓")


def v75_all_pass():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "replay.py")],
        capture_output=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert r.stdout and "[ALL PASS]" in r.stdout, f"V7.5 replay 未全过:\n{r.stdout[-500:]}"
    print(f"[V7.5] 全 fixture replay [ALL PASS] ✓")


def main():
    for fn in (v71_buy, v72_use, v73_limit, v74_budget, v75_all_pass):
        fn()
    print(f"\n{'='*40}")
    print("[M7 ALL PASS]")


if __name__ == "__main__":
    main()
