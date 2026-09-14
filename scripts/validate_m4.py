"""M4 专项验收：V4.1-V4.4 价格推理。"""
import json
import sys
import subprocess
import os
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "CoreGeek" / "src"))

from agent.brain import _MEM, decide  # noqa: E402
from agent.protocol import Turn  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def v41_unavailable_days():
    """V4.1: 铁矿塌方消息 → memory 标记 iron 不可采 day+1,day+2。"""
    _MEM.__init__()
    payload = json.loads((FIX / "day_news.json").read_text(encoding="utf-8"))
    turn = Turn.load(payload)
    print(f"[V4.1] officialNews={turn.world_news.official_news[:30]!r}...")
    assert "铁" in turn.world_news.official_news and "塌方" in turn.world_news.official_news
    decide(payload)
    iron_unavail = _MEM.ore_unavailable_days.get("iron", set())
    print(f"[V4.1] iron 不可采天数 = {sorted(iron_unavail)} (day={_MEM.day})")
    assert 2 in iron_unavail and 3 in iron_unavail, f"未标记 iron 不可采 day2,3: {iron_unavail}"
    print("[V4.1] PASS: 铁矿塌方→iron 不可采 {2,3} ✓")


def v42_sell_premium():
    """V4.2: iron涨价(price10)→优先卖iron(value10>stone value5)。"""
    _MEM.__init__()
    payload = json.loads((FIX / "day_sell_premium.json").read_text(encoding="utf-8"))
    decide(payload)
    cmd = _last_worker_cmd(payload, 10010)
    assert cmd and cmd["action"] == "sell", f"V4.2 未卖矿: {cmd}"
    assert cmd["name"] == "iron", f"V4.2 期望卖iron(涨价), 实际卖 {cmd['name']}"
    print(f"[V4.2] 涨价日优先卖 iron (price=10) ✓")


def v43_collect_ore():
    """V4.3: iron明天不可采→今天优先采iron囤货。"""
    _MEM.__init__()
    payload = json.loads((FIX / "day_news.json").read_text(encoding="utf-8"))
    decide(payload)
    cmd = _last_worker_cmd(payload, 10010)
    assert cmd and cmd["action"] == "collect", f"V4.3 未采集: {cmd}"
    target = cmd["targetPos"][0]
    # iron 矿在 (8,28), worker1@(8,27) 应采 (8,28)
    assert target == {"x": 8, "y": 28}, f"V4.3 期望采iron(8,28), 实际 {target}"
    print(f"[V4.3] iron 明天不可采→今天囤采 (8,28) ✓")


def v44_all_pass():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "replay.py")],
        capture_output=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert r.stdout and "[ALL PASS]" in r.stdout, f"V4.4 replay 未全过:\n{r.stdout[-500:]}"
    count = r.stdout.count("[OK] pass")
    print(f"[V4.4] 全 {count} fixture replay [ALL PASS] ✓")


def _last_worker_cmd(payload, worker_id):
    """重新跑 decide 取该 worker 命令（_MEM 已更新）。"""
    resp = decide(payload)
    return resp.role_command_map.get(str(worker_id))


def main():
    for fn in (v41_unavailable_days, v42_sell_premium, v43_collect_ore, v44_all_pass):
        fn()
    print(f"\n{'='*40}")
    print("[M4 ALL PASS]")


if __name__ == "__main__":
    main()
