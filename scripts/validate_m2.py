"""M2 专项验收：V2.5 双层围墙格数 + V2.7 memory 记录。"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "CoreGeek" / "src"))

from agent import builder  # noqa: E402
from agent.brain import _MEM, decide  # noqa: E402
from agent.protocol import Turn  # noqa: E402


def check_v25():
    """V2.5: wall_order 返回双层围墙格数 > 单层环。"""
    payload = json.loads((ROOT / "tests" / "fixtures" / "day_wall.json").read_text(encoding="utf-8"))
    turn = Turn.load(payload)
    order = builder.wall_order(turn)
    # 单层环约 20 格，双层应 > 35
    single_layer_estimate = 20
    print(f"[V2.5] wall_order 格数 = {len(order)} (单层参考 {single_layer_estimate})")
    assert len(order) > 35, f"双层围墙格数 {len(order)} 未明显超过单层"
    # 验证含两个 layer 的 y 坐标（d=2 的 y=21/26，d=3 的 y=20/27）
    ys = {p.y for p in order}
    assert 20 in ys or 27 in ys, f"缺少外层(d=3)坐标，ys={sorted(ys)}"
    print("[V2.5] PASS: 双层围墙布局确认")
    return True


def check_v27():
    """V2.7: officialNews 非空时 memory 记录 news_history + price_history。"""
    _MEM.__init__()  # 重置单例
    payload = json.loads((ROOT / "tests" / "fixtures" / "day_build.json").read_text(encoding="utf-8"))
    turn = Turn.load(payload)
    print(f"[V2.7] officialNews = {turn.world_news.official_news!r}")
    assert turn.world_news.official_news, "officialNews 为空"
    decide(payload)  # 触发 memory.update
    print(f"[V2.7] news_history 记录数 = {len(_MEM.news_history)}")
    print(f"[V2.7] price_history 矿种 = {list(_MEM.price_history.keys())}")
    for ore, hist in _MEM.price_history.items():
        print(f"       {ore}: {[(p.day, p.price) for p in hist]}")
    assert len(_MEM.news_history) > 0, "news_history 未记录"
    assert "stone" in _MEM.price_history and len(_MEM.price_history["stone"]) > 0, "price_history 未记录"
    print("[V2.7] PASS: memory 记录 news_history + price_history")
    return True


def main():
    ok = True
    ok = check_v25() and ok
    ok = check_v27() and ok
    print(f"\n{'='*40}")
    print("[M2 EXTRA PASS]" if ok else "[M2 EXTRA FAIL]")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
