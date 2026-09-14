"""从 docs/request.txt 派生 M2 验收用的白天场景 fixture。

场景:
  day_build   round5  白天早期建塔建墙(无塔无墙, gold75)
  day_sell    round15 小贩旁卖矿(worker背包满stone)
  day_buy     round25 商店旁买券(gold120, 有gatling level1)
  day_upgrade round26 武器旁用券升级(worker背包含Voucher1, 在gatling旁)
  night_attack round85 夜晚(原 request.txt)
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures"
FIXTURE_DIR.mkdir(parents=True, exist_ok=True)


def role(rid, x, y, rtype, hp, *, level=0, backpack=None, capacity=0,
         attack_power=0, attack_range=0, cooldown=0):
    return {
        "id": rid, "pos": {"x": x, "y": y}, "roleType": rtype,
        "health": hp, "attackPower": attack_power, "attackRange": attack_range,
        "level": level, "cooldown": cooldown,
        "backPackCapability": capacity, "backpack": backpack or [],
    }


def robot(rid, x, y, rtype, hp, state="", target="challenger"):
    return {
        "id": rid, "pos": {"x": x, "y": y}, "roleType": rtype,
        "health": hp, "abnormalState": state, "targetTeam": target,
    }


def make(name, round_no, gold, roles, robots=None, phase_task=""):
    base = json.loads((ROOT / "docs" / "request.txt").read_text(encoding="utf-8"))
    base["roundNo"] = round_no
    base["teamOur"]["goldNum"] = gold
    base["teamOur"]["roles"] = roles
    base["phaseTask"] = phase_task
    base["robot"]["roles"] = robots or []
    base["llmResp"] = ""
    base["lastCmdResult"] = ""
    base["lastSummonTreasureResult"] = 0
    base["lastRoundRoleActionResults"] = {}
    base["errors"] = []
    out = FIXTURE_DIR / f"{name}.json"
    out.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {out.name}: round {round_no} roles={len(roles)} gold={gold}")


def gen_day_build():
    """round5 白天, gold75(够3塔), 无武器无墙.
    worker1@(9,21)邻塔位(9,22)建gatling, worker2@(8,23)邻塔位(9,23)建railgun。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10010, 9, 21, "worker", 220, capacity=100),
        role(10012, 8, 23, "worker", 220, capacity=100),
        role(10011, 12, 25, "pioneer", 200, capacity=40),
    ]
    make("day_build", 5, 75, roles)


def gen_day_wall():
    """round8 白天, 3塔已建(无towers_missing), worker@(12,21)背包含stone, 邻墙位(13,21)建墙。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 22, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10030, 9, 23, "railgun", 1000, level=1, attack_power=10, attack_range=6),
        role(10040, 9, 24, "rocket", 1000, level=1, attack_power=20, attack_range=10),
        role(10010, 12, 21, "worker", 220, capacity=100, backpack=["stone"] * 3),
        role(10012, 10, 20, "worker", 220, capacity=100),
        role(10011, 10, 12, "pioneer", 200, capacity=40),
    ]
    make("day_wall", 8, 25, roles)


def gen_day_sell():
    """round15 白天, worker1在小贩(20,16)旁(19,16), 背包6个stone待卖。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 24, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10010, 19, 16, "worker", 220, capacity=100, backpack=["stone"] * 6),
        role(10012, 10, 20, "worker", 220, capacity=100),
        role(10011, 10, 12, "pioneer", 200, capacity=40),
    ]
    make("day_sell", 15, 10, roles)


def gen_day_buy():
    """round25 白天, worker1在商店(25,20)旁(24,20), gold120够买WeaponUpgradeVoucher1=100。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 24, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10010, 24, 20, "worker", 220, capacity=100),
        role(10012, 10, 20, "worker", 220, capacity=100),
        role(10011, 10, 12, "pioneer", 200, capacity=40),
    ]
    make("day_buy", 25, 120, roles)


def gen_day_upgrade():
    """round26 白天, worker1在gatling(9,24)旁(8,24), 背包有WeaponUpgradeVoucher1, 待use升级。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 24, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10010, 8, 24, "worker", 220, capacity=100, backpack=["WeaponUpgradeVoucher1"]),
        role(10012, 10, 20, "worker", 220, capacity=100),
        role(10011, 10, 12, "pioneer", 200, capacity=40),
    ]
    make("day_upgrade", 26, 20, roles)


def gen_day_summon_buy():
    """round20 白天, worker1在商店(25,20)旁(24,20), gold300, 无升级目标(全满级)→买召唤令。"""
    roles = [
        role(10013, 10, 24, "station", 4500, level=3),
        role(10020, 9, 22, "gatling", 2000, level=3, attack_power=10, attack_range=7),
        role(10030, 9, 23, "railgun", 2000, level=3, attack_power=30, attack_range=10),
        role(10040, 9, 24, "rocket", 2000, level=3, attack_power=20, attack_range=2147483647),
        role(10010, 24, 20, "worker", 220, capacity=100),
        role(10012, 10, 20, "worker", 220, capacity=100),
        role(10011, 10, 12, "pioneer", 200, capacity=40),
    ]
    make("day_summon_buy", 20, 300, roles)


def gen_day_summon_use():
    """round21 白天, worker1背包含SmallRobotSummonOrder→使用。"""
    roles = [
        role(10013, 10, 24, "station", 4500, level=3),
        role(10020, 9, 22, "gatling", 2000, level=3, attack_power=10, attack_range=7),
        role(10030, 9, 23, "railgun", 2000, level=3, attack_power=30, attack_range=10),
        role(10040, 9, 24, "rocket", 2000, level=3, attack_power=20, attack_range=2147483647),
        role(10010, 24, 20, "worker", 220, capacity=100, backpack=["SmallRobotSummonOrder"]),
        role(10012, 10, 20, "worker", 220, capacity=100),
        role(10011, 10, 12, "pioneer", 200, capacity=40),
    ]
    make("day_summon_use", 21, 300, roles)


def gen_day_summon_limit():
    """round22 白天, 已用8张(memory预设), gold300→只能再买2张后停。"""
    roles = [
        role(10013, 10, 24, "station", 4500, level=3),
        role(10020, 9, 22, "gatling", 2000, level=3, attack_power=10, attack_range=7),
        role(10030, 9, 23, "railgun", 2000, level=3, attack_power=30, attack_range=10),
        role(10040, 9, 24, "rocket", 2000, level=3, attack_power=20, attack_range=2147483647),
        role(10010, 24, 20, "worker", 220, capacity=100, backpack=["SmallRobotSummonOrder"]),
        role(10012, 10, 20, "worker", 220, capacity=100),
        role(10011, 10, 12, "pioneer", 200, capacity=40),
    ]
    make("day_summon_limit", 22, 300, roles)


def gen_day_summon_budget():
    """round23 白天, gold60(不足买小令后保50), worker在商店旁→不买(保预算)。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 22, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10010, 24, 20, "worker", 220, capacity=100),
        role(10012, 10, 20, "worker", 220, capacity=100),
        role(10011, 10, 12, "pioneer", 200, capacity=40),
    ]
    make("day_summon_budget", 23, 60, roles)


def gen_night_move():
    """round85 夜晚, 原始 request.txt (角色走向武器, 回归移动)。"""
    base = json.loads((ROOT / "docs" / "request.txt").read_text(encoding="utf-8"))
    out = FIXTURE_DIR / "night_move.json"
    out.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {out.name}: round {base['roundNo']} (copy)")


def gen_night_attack():
    """round71 首夜, 3角色已在3武器旁, 4机器人(含BOSS)进射程。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 24, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10030, 10, 25, "railgun", 1000, level=1, attack_power=10, attack_range=6),
        role(10040, 9, 25, "rocket", 1000, level=1, attack_power=20, attack_range=10),
        role(10010, 8, 24, "worker", 220, capacity=100),
        role(10012, 10, 26, "worker", 220, capacity=100),
        role(10011, 8, 26, "pioneer", 200, capacity=40),
    ]
    robots = [
        robot(30001, 11, 22, "smallRobot", 40),
        robot(30002, 12, 23, "middleRobot", 60),
        robot(30003, 13, 24, "largeRobot", 500),
        robot(30004, 11, 21, "bossRobot", 800),
    ]
    make("night_attack", 71, 20, roles, robots)


def gen_night_gatling():
    """round71 首夜, gatling level2(2目标), 2小型机器人同锥+1异向。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 24, "gatling", 1000, level=2, attack_power=10, attack_range=5),
        role(10010, 8, 24, "worker", 220, capacity=100),
        role(10012, 10, 26, "worker", 220, capacity=100),
        role(10011, 8, 26, "pioneer", 200, capacity=40),
    ]
    robots = [
        robot(30001, 11, 22, "smallRobot", 40),   # 方向(2,-2)
        robot(30002, 12, 22, "smallRobot", 40),   # 方向(3,-2) 同锥
        robot(30003, 15, 25, "smallRobot", 40),   # 方向(6,0) 异向,且超range5
    ]
    make("night_gatling", 71, 20, roles, robots)


def gen_night_railgun():
    """round71 首夜, railgun level1, 3机器人共线(x轴)可穿透。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10030, 10, 25, "railgun", 1000, level=1, attack_power=10, attack_range=6),
        role(10012, 10, 26, "worker", 220, capacity=100),
        role(10010, 8, 24, "worker", 220, capacity=100),
        role(10011, 8, 26, "pioneer", 200, capacity=40),
    ]
    robots = [
        robot(30001, 12, 25, "smallRobot", 40),  # 距2
        robot(30002, 14, 25, "middleRobot", 60),  # 距4
        robot(30003, 16, 25, "largeRobot", 500),  # 距6 共线
    ]
    make("night_railgun", 71, 20, roles, robots)


def gen_night_rocket():
    """round71 首夜, rocket level1, 3机器人聚集+1远, 选聚类落点。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10040, 9, 25, "rocket", 1000, level=1, attack_power=20, attack_range=10),
        role(10011, 8, 26, "pioneer", 200, capacity=40),
        role(10010, 8, 24, "worker", 220, capacity=100),
        role(10012, 10, 26, "worker", 220, capacity=100),
    ]
    robots = [
        robot(30001, 15, 25, "smallRobot", 40),   # 聚集
        robot(30002, 16, 25, "smallRobot", 40),   # 聚集
        robot(30003, 15, 26, "smallRobot", 40),  # 聚集(3×3覆盖3)
        robot(30004, 19, 25, "smallRobot", 40),  # 远离单只
    ]
    make("night_rocket", 71, 20, roles, robots)


def gen_day_news():
    """round10 白天, 官方消息含'铁矿塌方', 3塔已建(无建塔任务), worker1旁iron矿(8,28)待囤采。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 22, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10030, 9, 23, "railgun", 1000, level=1, attack_power=10, attack_range=6),
        role(10040, 9, 24, "rocket", 1000, level=1, attack_power=20, attack_range=10),
        role(10010, 8, 27, "worker", 220, capacity=100),
        role(10012, 10, 20, "worker", 220, capacity=100),
        role(10011, 10, 12, "pioneer", 200, capacity=40),
    ]
    make("day_news", 10, 25, roles)
    p = FIXTURE_DIR / "day_news.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["worldNews"]["officialNews"] = (
        "矿业管理局通报：北部铁矿区昨夜发生严重塌方事故，"
        "主巷道结构受损。矿区明日全面停工，修复工程需2天。"
    )
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  day_news.json: officialNews 覆盖为铁矿塌方")


def gen_day_collect():
    """round10 白天, 无塌方消息, worker1旁iron矿(8,28)+stone矿(4,24)远,
    验证默认采高价矿(copper>iron>stone 但只iron邻)→采iron。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 24, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10010, 8, 27, "worker", 220, capacity=100),
        role(10012, 10, 20, "worker", 220, capacity=100),
        role(10011, 10, 12, "pioneer", 200, capacity=40),
    ]
    make("day_collect", 10, 25, roles)


def gen_day_sell_premium():
    """round15 白天, iron涨价(price=10), worker1在小贩旁含1iron+5stone,
    验证优先卖涨价iron(value10>stone value5)。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 24, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10010, 19, 16, "worker", 220, capacity=100,
             backpack=["iron", "stone", "stone", "stone", "stone", "stone"]),
        role(10012, 10, 20, "worker", 220, capacity=100),
        role(10011, 10, 12, "pioneer", 200, capacity=40),
    ]
    make("day_sell_premium", 15, 10, roles)
    p = FIXTURE_DIR / "day_sell_premium.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for item in data["vendorShopList"]:
        if item["name"] == "iron":
            item["price"] = 10
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  day_sell_premium.json: iron 涨价 price=10")


# ===== 真实对战基础用例（基于 request.txt 真实地图）=====

def gen_real_day_init():
    """round1 白天初始, challenger 真实开局: station@10,24, 2worker+pioneer 在基地旁,
    无塔无墙, gold75. 验证白天产出≥2命令(建塔/采集/移动), 不再0 cmds。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10010, 12, 24, "worker", 220, capacity=100),
        role(10012, 12, 23, "worker", 220, capacity=100),
        role(10011, 12, 25, "pioneer", 200, capacity=40),
    ]
    make("real_day_init", 1, 75, roles)


def gen_real_night_wave():
    """round71 首夜, 3塔已建(基地旁真实塔位9,22/9,23/9,24), 角色在塔旁,
    机器人来袭(含BOSS). 验证夜间attack操控武器。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 22, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10030, 9, 23, "railgun", 1000, level=1, attack_power=10, attack_range=6),
        role(10040, 9, 24, "rocket", 1000, level=1, attack_power=20, attack_range=10),
        role(10010, 8, 22, "worker", 220, capacity=100),
        role(10012, 8, 23, "worker", 220, capacity=100),
        role(10011, 8, 24, "pioneer", 200, capacity=40),
    ]
    robots = [
        robot(30001, 11, 22, "smallRobot", 40),
        robot(30002, 12, 23, "middleRobot", 60),
        robot(30003, 11, 21, "bossRobot", 800),
    ]
    make("real_night_wave", 71, 20, roles, robots)


def gen_real_task_accept():
    """round10 白天, pioneer@13,14邻challengerTaskPoint1@(14,14), playerTasks可接.
    验证acceptTask(自进化任务入口)。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 22, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10030, 9, 23, "railgun", 1000, level=1, attack_power=10, attack_range=6),
        role(10040, 9, 24, "rocket", 1000, level=1, attack_power=20, attack_range=10),
        role(10010, 8, 22, "worker", 220, capacity=100),
        role(10012, 8, 23, "worker", 220, capacity=100),
        role(10011, 13, 14, "pioneer", 200, capacity=40),
    ]
    make("real_task_accept", 10, 25, roles)


def gen_real_folk_legend():
    """round1 白天, 真实民间传闻(西部有一石门,门需三钥). 验证treasure.dispatch_llm产出prompt。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10010, 12, 24, "worker", 220, capacity=100),
        role(10012, 12, 23, "worker", 220, capacity=100),
        role(10011, 12, 25, "pioneer", 200, capacity=40),
    ]
    make("real_folk_legend", 1, 75, roles)


def gen_night_items():
    """round71 首夜, BOSS进range, worker1背包含DizzyWeapon待用, worker2操控railgun。"""
    roles = [
        role(10013, 10, 24, "station", 1500, level=1),
        role(10020, 9, 24, "gatling", 1000, level=1, attack_power=10, attack_range=3),
        role(10030, 10, 25, "railgun", 1000, level=1, attack_power=10, attack_range=6),
        role(10010, 8, 24, "worker", 220, capacity=100, backpack=["DizzyWeapon"]),
        role(10012, 10, 26, "worker", 220, capacity=100),
        role(10011, 8, 26, "pioneer", 200, capacity=40),
    ]
    robots = [
        robot(30004, 11, 24, "bossRobot", 800),  # gatling range内(距2)
    ]
    make("night_items", 71, 120, roles, robots)


def main():
    print("Generating fixtures:")
    gen_day_build()
    gen_day_wall()
    gen_day_sell()
    gen_day_buy()
    gen_day_upgrade()
    gen_day_news()
    gen_day_collect()
    gen_day_sell_premium()
    gen_day_summon_buy()
    gen_day_summon_use()
    gen_day_summon_limit()
    gen_day_summon_budget()
    gen_night_move()
    gen_night_attack()
    gen_night_gatling()
    gen_night_railgun()
    gen_night_rocket()
    gen_night_items()
    # 真实对战基础用例
    gen_real_day_init()
    gen_real_night_wave()
    gen_real_task_accept()
    gen_real_folk_legend()
    print(f"Done -> {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
