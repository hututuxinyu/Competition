"""行为快照回归（止血）：对每个 fixture 在独立子进程跑 decide()，
将规范化输出与基线对比，任何非预期行为变化立即暴露。

用法:
  py -3.11 scripts/snapshot.py            # check（默认）：对比基线，有变化 → 退出码 1
  py -3.11 scripts/snapshot.py --update   # 重建/更新基线（预期变化时手动跑，随代码一起提交）

变更即风险：改动若导致其它 fixture 输出 diff，说明牵连了既有行为，需复核。
"""
import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures"
SNAP_DIR = ROOT / "tests" / "snapshots"
WORKER = ROOT / "scripts" / "_snapshot_worker.py"


def run_worker(payload_text: str) -> str:
    """子进程跑 decide()，返回规范化 JSON 文本。用 bytes 模式读取，避免
    Windows 子进程 stderr 默认 GBK 编码导致解码失败而掩盖真实错误。"""
    proc = subprocess.run(
        [sys.executable, str(WORKER)],
        input=payload_text.encode("utf-8"),
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"worker 退出 {proc.returncode}\nstderr:\n{err}")
    return proc.stdout.decode("utf-8")


def canonicalize(json_text: str) -> str:
    """二次规范化，抹平 worker 与基线间可能的格式差异。"""
    obj = json.loads(json_text)
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def fixture_paths() -> list[Path]:
    if not FIXTURE_DIR.exists():
        return []
    return sorted(FIXTURE_DIR.glob("*.json"))


def do_update() -> int:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in fixture_paths():
        out = canonicalize(run_worker(p.read_text(encoding="utf-8")))
        (SNAP_DIR / f"{p.stem}.json").write_text(out, encoding="utf-8")
        print(f"  [snapshot] {p.name} -> tests/snapshots/{p.stem}.json")
        n += 1
    print(f"\n[OK] 已写 {n} 份基线到 tests/snapshots/")
    return 0


def do_check() -> int:
    if not SNAP_DIR.exists():
        print("[ERROR] 无基线：先跑 `py -3.11 scripts/snapshot.py --update`")
        return 2
    same = 0
    changed: list[tuple[str, str]] = []
    for p in fixture_paths():
        snap_path = SNAP_DIR / f"{p.stem}.json"
        if not snap_path.exists():
            changed.append((p.name, f"<基线缺失 tests/snapshots/{p.stem}.json>"))
            continue
        try:
            current = canonicalize(run_worker(p.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            changed.append((p.name, f"<worker 异常: {e}>"))
            continue
        base = snap_path.read_text(encoding="utf-8")
        if current == base:
            same += 1
            print(f"  [SAME]   {p.name}")
        else:
            diff = "".join(difflib.unified_diff(
                base.splitlines(keepends=True),
                current.splitlines(keepends=True),
                fromfile=f"base/{p.stem}.json",
                tofile=f"cur/{p.stem}.json",
                n=1,
            ))
            changed.append((p.name, diff))
            print(f"  [CHANGED] {p.name}")
    print(f"\n{'='*50}")
    print(f"结果：{same} same / {len(changed)} changed")
    if changed:
        print("\n—— 变更明细（预期则 `--update` 更新基线并提交；非预期则需复盘）——")
        for name, diff in changed:
            print(f"\n### {name}")
            if diff.startswith("<"):
                print(diff)
            else:
                print(diff.rstrip())
        print("\n[FAIL] 存在行为变化，请确认是否预期。")
        return 1
    print("[ALL SAME] 无回归。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="行为快照回归")
    ap.add_argument("--update", action="store_true", help="更新/重建基线")
    args = ap.parse_args()
    if args.update:
        return do_update()
    return do_check()


if __name__ == "__main__":
    sys.exit(main())
