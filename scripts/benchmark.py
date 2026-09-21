"""多回合战略KPI基准测试：模拟130回合游戏进程，追踪战略指标 + score估算。

用法:
  py -3.11 scripts/benchmark.py            # check：对比基线，有退化 → 退出码 1
  py -3.11 scripts/benchmark.py --update    # 重建基线（预期变化时手动跑）

核心思路：用简化MockJudge模拟游戏进程，对decide()的输出做战略KPI评估，
而非逐字节JSON对比。KPI退化 = 退化风险，必须复盘。

KPI清单（按score贡献排序）:
  P0 任务: acceptTask次数、submitAnswer次数
  P2 建塔: R10前塔数(目标3)、塔类型(rocket优先)
  P1 经济: R70金币(目标80+)、卖矿次数
  P3 基地: 基地等级(目标R130前Lv2=3000HP)
  P4 塔升级: 塔Lv2数量(目标R70前≥1)
  生存: 基地HP>0的回合数 → score3估算
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "scripts" / "_bench_worker.py"
BASELINE_DIR = ROOT / "tests" / "bench_baseline"


# —— KPI 定义与评估 ——
# 每条: (名称, 检查轮次, 目标值, 比较方向, 描述)
# 比较方向: ">=" 至少达到, "<=" 不超过, "==" 精确
KPI_TARGETS: list[tuple[str, int, Any, str, str]] = [
    # P2: 三塔前置（score3生存保障）
    ("tower_count_r10", 10, 3, ">=", "R10前应建满3座塔"),
    ("tower_count_r30", 30, 3, ">=", "R30应保持3座塔"),
    ("rocket_ratio_r10", 10, 1.0, ">=", "R10塔中rocket占比（越高越好）"),
    # P1: 经济节奏
    ("gold_r30", 30, 25, ">=", "R30金币应≥25（起始值回收）"),
    ("gold_r70", 70, 40, ">=", "R70金币应≥40"),
    ("sell_count_r70", 70, 3, ">=", "R70前应至少卖矿3次"),
    # P0: 任务系统
    ("task_accept_count_r70", 70, 1, ">=", "R70前应至少接1个任务"),
    ("task_submit_count_r70", 70, 1, ">=", "R70前应至少提交1次答案"),
    # P3: 基地升级（需260回合=2天，Day2经济支撑）
    ("base_level_r130", 130, 1, ">=", "R130基地应存活(Lv1+)"),
    ("base_level_r260", 260, 2, ">=", "R260基地应升至Lv2(3000HP)"),
    # P4: 塔升级
    ("tower_lv2_count_r260", 260, 1, ">=", "R260前至少1座塔升Lv2"),
    # 生存
    ("base_alive_r130", 130, 1, "==", "R130基地应存活"),
    ("wall_count_r70", 70, 5, ">=", "R70前应至少建5墙"),
    # 0-cmd 检查
    ("zero_cmd_rounds_r70", 70, 5, "<=", "R70前0-cmd回合数应≤5"),
]


def run_worker(base_fixture: Path) -> str:
    """子进程跑模拟，返回 KPI JSON 文本。bytes 模式避免 GBK 问题。"""
    proc = subprocess.run(
        [sys.executable, str(WORKER)],
        input=base_fixture.read_bytes(),
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"worker 退出 {proc.returncode}\nstderr:\n{err}")
    return proc.stdout.decode("utf-8")


def evaluate_kpis(kpi_data: dict[str, Any]) -> list[dict[str, Any]]:
    """评估每条 KPI 目标，返回结果列表。"""
    results = []
    for name, round_no, target, op, desc in KPI_TARGETS:
        actual = kpi_data.get(name)
        if actual is None:
            results.append({
                "kpi": name, "round": round_no, "target": target,
                "actual": None, "pass": False, "desc": desc,
                "error": "KPI缺失",
            })
            continue
        if op == ">=":
            ok = actual >= target
        elif op == "<=":
            ok = actual <= target
        elif op == "==":
            ok = actual == target
        else:
            ok = False
        results.append({
            "kpi": name, "round": round_no, "target": target,
            "actual": actual, "pass": ok, "desc": desc,
        })
    return results


def estimate_score(kpi_data: dict[str, Any]) -> dict[str, int]:
    """估算 score 三大组成（粗估，用于趋势对比）。"""
    # score1: 任务积分（每个完成任务约50分 + 速度奖励）
    task_done = kpi_data.get("task_submit_count_r70", 0)
    score1 = task_done * 55  # 50基础 + ~5速度奖励

    # score2: 作战击杀（粗估：每夜存活 = 杀光该夜机器人）
    # 夜晚存活回合越多 = 杀怪越多。Day1夜杀怪≈5分, Day2≈10, 递增
    base_alive_r130 = kpi_data.get("base_alive_r130", 0)
    nights_survived = 0
    if base_alive_r130:
        nights_survived = 1  # 至少活过第1夜
    score2 = nights_survived * 15  # 粗估

    # score3: 生存天数积分 = Σ(10 × day × 存活系数)
    # 活到R130 = 活过Day1 = 10×1=10
    score3 = 10 if base_alive_r130 else 0

    return {"score1": score1, "score2": score2, "score3": score3,
            "total": score1 + score2 + score3}


def do_check() -> int:
    base_path = ROOT / "tests" / "fixtures" / "real_day_init.json"
    if not base_path.exists():
        print("[ERROR] 缺少基准 fixture real_day_init.json")
        return 2

    baseline_path = BASELINE_DIR / "kpi_baseline.json"
    if not baseline_path.exists():
        print("[ERROR] 无基线：先跑 `py -3.11 scripts/benchmark.py --update`")
        return 2

    print("运行模拟中（130回合）...")
    raw = run_worker(base_path)
    current = json.loads(raw)

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    # KPI 目标评估
    cur_results = evaluate_kpis(current)
    base_results = evaluate_kpis(baseline)

    print(f"\n{'='*70}")
    print("战略KPI基准报告")
    print(f"{'='*70}")

    all_pass = True
    regressions = []

    print(f"\n{'KPI':<28} {'目标':>6} {'当前':>8} {'基线':>8} {'目标':>5} {'趋势':>5} {'描述'}")
    print("-" * 100)

    for cur, base in zip(cur_results, base_results):
        kpi = cur["kpi"]
        target = cur["target"]
        c_val = cur["actual"]
        b_val = base["actual"]

        # 目标检查
        tgt_pass = "PASS" if cur["pass"] else "FAIL"
        if not cur["pass"]:
            all_pass = False

        # 趋势检查（对比基线）
        if isinstance(c_val, (int, float)) and isinstance(b_val, (int, float)):
            if c_val > b_val:
                trend = "↑"
            elif c_val < b_val:
                trend = "↓"
                # 退化检查：当前比基线差
                if kpi not in ("zero_cmd_rounds_r70",):  # zero_cmd 越少越好
                    regressions.append(
                        f"{kpi}: {b_val} → {c_val} (退化)")
            else:
                trend = "="
        else:
            trend = "?"

        print(f"{kpi:<28} {str(target):>6} {str(c_val):>8} {str(b_val):>8} "
              f"{tgt_pass:>5} {trend:>5} {cur['desc']}")

    # score 估算
    cur_score = estimate_score(current)
    base_score = estimate_score(baseline)
    print(f"\n{'— Score估算 —':}")
    print(f"  score1(任务): {cur_score['score1']}  (基线: {base_score['score1']})")
    print(f"  score2(击杀): {cur_score['score2']}  (基线: {base_score['score2']})")
    print(f"  score3(生存): {cur_score['score3']}  (基线: {base_score['score3']})")
    print(f"  total:        {cur_score['total']}  (基线: {base_score['total']})")

    if cur_score["total"] < base_score["total"]:
        regressions.append(
            f"score估算退化: {base_score['total']} → {cur_score['total']}")
        all_pass = False

    # 模拟时序摘要
    timeline = current.get("timeline", {})
    if timeline:
        print(f"\n{'— 关键时序 —'}")
        for key in ("first_tower_round", "third_tower_round",
                    "first_wall_round", "first_sell_round",
                    "first_accept_task_round",
                    "first_submit_answer_round",
                    "base_upgrade_round",
                    "first_tower_upgrade_round"):
            val = timeline.get(key)
            if val is not None:
                print(f"  {key}: R{val}")

    if regressions:
        print(f"\n[FAIL] {len(regressions)} 项退化:")
        for r in regressions:
            print(f"  - {r}")
        return 1

    if all_pass:
        print(f"\n[ALL PASS] 所有KPI达标，无退化。")
        return 0
    else:
        failed = [r for r in cur_results if not r["pass"]]
        print(f"\n[WARN] {len(failed)} 项KPI未达标（但无退化）:")
        for r in failed:
            print(f"  - {r['kpi']}: 目标{r['target']}, 实际{r['actual']} ({r['desc']})")
        return 0  # 未达标但无退化 = 退出0，仅信息提示


def do_update() -> int:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    base_path = ROOT / "tests" / "fixtures" / "real_day_init.json"
    if not base_path.exists():
        print("[ERROR] 缺少基准 fixture real_day_init.json")
        return 2

    print("运行模拟中（130回合）...")
    raw = run_worker(base_path)
    current = json.loads(raw)

    out = BASELINE_DIR / "kpi_baseline.json"
    out.write_text(
        json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    results = evaluate_kpis(current)
    score = estimate_score(current)
    print(f"\n[OK] 基线已写入 {out}")
    print(f"\nKPI概览:")
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  [{status}] {r['kpi']}: {r['actual']} (目标{r['op'] if 'op' in r else ''}{r['target']}) — {r['desc']}")
    print(f"\nScore估算: total={score['total']} (s1={score['score1']}, s2={score['score2']}, s3={score['score3']})")
    return 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="多回合战略KPI基准测试")
    ap.add_argument("--update", action="store_true", help="更新/重建基线")
    args = ap.parse_args()
    if args.update:
        return do_update()
    return do_check()


if __name__ == "__main__":
    sys.exit(main())
