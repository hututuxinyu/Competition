"""本地回放验证框架：用 docs/request.txt 模拟判题器请求，验证 decide 全链路。

用法: python scripts/replay.py [path/to/request.json ...]
不传参数则回放 docs/request.txt。
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "CoreGeek" / "src"))

from agent.brain import decide  # noqa: E402
from agent.protocol import Turn  # noqa: E402


def validate_response(response, round_no: int) -> list[str]:
    """校验响应格式合法性，返回错误列表（空=通过）。"""
    errors = []
    out = response.to_dict()
    for key in ("roleCommandMap", "prompt", "executeCmd"):
        if key not in out:
            errors.append(f"round {round_no}: 缺少字段 {key}")
    for rid, cmd in out["roleCommandMap"].items():
        if not isinstance(cmd, dict):
            errors.append(f"round {round_no} role {rid}: 命令不是 dict")
            continue
        if "action" not in cmd:
            errors.append(f"round {round_no} role {rid}: 缺少 action")
        action = cmd.get("action")
        legal = {
            "move", "attack", "sell", "buy", "build", "remove",
            "acceptTask", "submitAnswer", "summonTreasure", "use", "drop", "collect",
        }
        if action not in legal:
            errors.append(f"round {round_no} role {rid}: 非法 action={action!r}")
    return errors


def replay_one(path: Path) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    turn = Turn.load(payload)
    print(f"\n=== {path.name} round {turn.round_no} (day {turn.day} {'day' if turn.is_day else 'night'}) ===")
    print(f"team={turn.team_type} gold={turn.gold} score={turn.total_score}")
    print(f"ours={len(turn.ours)} enemies={len(turn.enemies)} robots={len(turn.robots)} "
          f"tasks={len(turn.player_tasks)} zones={len(turn.zones)} errors={len(turn.errors)}")
    print(f"vendor_shop={len(turn.vendor_shop)} weapon_shop={len(turn.weapon_shop)}")
    print(f"news_official={turn.world_news.official_news[:50]!r}")
    print(f"news_folk={turn.world_news.folk_legends[:50]!r}")
    print(f"phase_task={turn.phase_task!r} llm_resp={turn.llm_resp!r} last_cmd={turn.last_cmd_result!r}")

    response = decide(payload)
    print(f"\nResponse: {len(response.role_command_map)} commands, "
          f"prompt={len(response.prompt)}B, executeCmd={len(response.execute_cmd)}B")
    for rid, cmd in response.role_command_map.items():
        print(f"  {rid}: {json.dumps(cmd, ensure_ascii=False)}")

    errors = validate_response(response, turn.round_no)
    if errors:
        print(f"\n[FAIL] {len(errors)} errors:")
        for e in errors:
            print(f"  - {e}")
        return False
    print("\n[OK] pass")
    return True


def main() -> None:
    args = sys.argv[1:]
    if not args:
        fixture_dir = ROOT / "tests" / "fixtures"
        paths = sorted(fixture_dir.glob("*.json")) if fixture_dir.exists() \
            else [ROOT / "docs" / "request.txt"]
    else:
        paths = [Path(a) for a in args]
    all_ok = True
    for p in paths:
        if not p.exists():
            print(f"文件不存在: {p}")
            all_ok = False
            continue
        all_ok = replay_one(p) and all_ok
    print(f"\n{'='*40}")
    print("[ALL PASS]" if all_ok else "[HAS FAIL]")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
