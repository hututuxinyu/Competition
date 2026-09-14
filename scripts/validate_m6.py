"""M6 专项验收：长上下文宝藏（V6.1-V6.7）。"""
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


def make_round(round_no, pioneer_pos, *, folk="", llm_resp="", last_summon=0,
               gold=100, backpack=None):
    p = copy.deepcopy(base)
    p["roundNo"] = round_no
    for r in p["teamOur"]["roles"]:
        if r["id"] == 10011:
            r["pos"] = {"x": pioneer_pos[0], "y": pioneer_pos[1]}
            if backpack is not None:
                r["backpack"] = backpack
    p["teamOur"]["goldNum"] = gold
    p["worldNews"]["folkLegends"] = folk
    p["llmResp"] = llm_resp
    p["lastSummonTreasureResult"] = last_summon
    p["phaseTask"] = ""
    p["lastCmdResult"] = ""
    p["lastRoundRoleActionResults"] = {}
    p["errors"] = []
    for pt in p["teamOur"]["playerTasks"]:
        pt["coldDownRounds"] = 30  # 不可接取，避免任务干扰
        pt["isValid"] = False
        pt["timeoutRounds"] = 50
    return p


def pioneer_cmd(resp):
    return resp.role_command_map.get("10011")


def main():
    _MEM.__init__()
    # R1: 民间传闻累积 → dispatch_llm 产出 prompt [V6.1/V6.2]
    resp1 = decide(make_round(10, (24, 20), folk="西部有石门，需三钥"))
    assert len(_MEM.folk_legend_log) > 0, "V6.1 民间传闻未累积"
    assert resp1.prompt != "", "V6.2 prompt 未产出"
    print(f"[V6.1] folk_legend_log 累积 {_MEM.folk_legend_log[-1][:20]!r} ✓")
    print(f"[V6.2] LLM 推断 prompt 产出 ✓")

    # R2: llmResp 假设 → 解析 hypothesis；pioneer 在商店旁买 AcientTablet [V6.3]
    hyp = '{"pos":{"x":9,"y":20},"items":["AcientTablet"],"time":"DAY2"}'
    resp2 = decide(make_round(11, (24, 20), llm_resp=hyp, gold=100))
    assert _MEM.treasure_hypothesis.get("pos") == {"x": 9, "y": 20}, "V6.3 hypothesis 未解析"
    c2 = pioneer_cmd(resp2)
    assert c2 and c2["action"] == "buy" and c2["name"] == "AcientTablet", f"V6.3 买用品失败: {c2}"
    print(f"[V6.3] llmResp 解析→hypothesis + 买 AcientTablet ✓")

    # R3: pioneer 携带用品到地点旁 → summonTreasure [V6.4]
    resp3 = decide(make_round(12, (9, 21), gold=100, backpack=["AcientTablet"]))
    c3 = pioneer_cmd(resp3)
    assert c3 and c3["action"] == "summonTreasure", f"V6.4 期望 summonTreasure, 实际 {c3}"
    assert c3["targetPos"][0] == {"x": 9, "y": 20}, f"V6.4 地点错: {c3}"
    assert c3["item"] == ["AcientTablet"], f"V6.4 物品错: {c3}"
    print(f"[V6.4] summonTreasure @(9,20) item=[AcientTablet] ✓")

    # R4: lastSummonTreasureResult=3(物品错) → 清假设重推断 [V6.5]
    resp4 = decide(make_round(13, (9, 21), last_summon=3, gold=100, backpack=["AcientTablet"]))
    assert not _MEM.treasure_hypothesis, f"V6.5 假设未清空: {_MEM.treasure_hypothesis}"
    assert resp4.prompt != "", "V6.5 未重新推断"
    print(f"[V6.5] 物品错(3)→清假设 + 重新 LLM 推断 ✓")

    # R5: 宝藏已开 → 停止尝试 [V6.6]
    _MEM.treasure_opened = True
    resp5 = decide(make_round(14, (9, 21), gold=100, backpack=["AcientTablet"]))
    c5 = pioneer_cmd(resp5)
    is_summon = c5 and c5.get("action") == "summonTreasure"
    assert not is_summon, f"V6.6 已开仍召唤: {c5}"
    assert resp5.prompt == "", "V6.6 已开仍产出 prompt"
    print(f"[V6.6] 宝藏已开→停止尝试 + 不再调 LLM ✓")

    # V6.7: 全 fixture replay
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "replay.py")],
        capture_output=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert r.stdout and "[ALL PASS]" in r.stdout, f"V6.7 replay 未全过:\n{r.stdout[-500:]}"
    print(f"[V6.7] 全 fixture replay [ALL PASS] ✓")

    print(f"\n{'='*40}")
    print("[M6 ALL PASS]")


if __name__ == "__main__":
    main()
