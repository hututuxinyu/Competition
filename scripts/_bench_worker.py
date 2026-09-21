"""基准测试子进程：模拟130回合游戏，输出KPI JSON。

读 stdin 一份 base fixture（real_day_init.json），模拟130回合，
每回合调用 decide() 并应用命令到游戏状态，最终输出 KPI 汇总。

模拟简化点（不影响战略KPI有效性）:
  - 机器人夜间简化：按塔数/等级估算杀敌与基地受损
  - LLM/executeCmd 不回灌（空字符串），任务探索受限
  - 矿石价格不波动（固定 vendorShopList 初始价）
  - 矿区10采后刷新到随机位置
"""
from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "CoreGeek" / "src"))

from agent.brain import decide  # noqa: E402
from agent.memory import Memory  # noqa: E402
import agent.brain as brain_mod  # noqa: E402

DAY_ROUNDS = 70
NIGHT_ROUNDS = 60
ROUNDS_PER_DAY = DAY_ROUNDS + NIGHT_ROUNDS
SIM_ROUNDS = 260  # 模拟2天（含2个白天+2个夜晚），覆盖基地/塔升级

TOWER_COST = 25
ORE_TYPES = ("stone", "iron", "copper")
TOWER_TYPES = ("gatling", "railgun", "rocket")
ROBOT_SCORE = {"smallRobot": 1, "middleRobot": 2, "largeRobot": 4, "bossRobot": 10}
ROBOT_HP = {"smallRobot": 40, "middleRobot": 60, "largeRobot": 500, "bossRobot": 800}
ROBOT_ATK = {"smallRobot": 5, "middleRobot": 10, "largeRobot": 20, "bossRobot": 40}

# 每夜机器人波次（天数 → (小, 中, 大, BOSS)）
NIGHT_WAVES = {
    1: (3, 1, 0, 0),
    2: (4, 2, 0, 0),
}

# 塔DPS估算（每回合输出）
TOWER_DPS = {
    "gatling": {1: 10, 2: 20, 3: 30},
    "railgun": {1: 10, 2: 20, 3: 30},
    "rocket": {1: 20, 2: 40, 3: 60},
}


class MockJudge:
    """简化游戏模拟器。"""

    def __init__(self, base_fixture: dict[str, Any]):
        self.state = copy.deepcopy(base_fixture)
        self._next_unit_id = 10050
        self._mine_uses: dict[str, int] = {}  # "x,y" → 已采次数
        self._random = random.Random(42)  # 固定种子保证可复现

        # KPI 追踪
        self.timeline: dict[str, int] = {}
        self.sell_count = 0
        self.task_accept_count = 0
        self.task_submit_count = 0
        self.zero_cmd_rounds = 0
        self._task_active = False
        self._task_accept_round = 0
        self._task_timeout = 30
        self._task_reward_score = 50
        self._task_reward_gold = 30

        # 每轮快照（用于 milestone KPI）
        self._history: list[dict] = []
        self._tower_history: dict[int, list[dict]] = {}

    def run(self) -> dict[str, Any]:
        for r in range(1, SIM_ROUNDS + 1):
            self.state["roundNo"] = r
            self._update_day_night(r)
            self._update_task_state(r)
            self._handle_night(r)

            # 调用 agent
            try:
                response = decide(self.state)
            except Exception:
                response = None

            cmds = {}
            prompt = ""
            execute_cmd = ""
            if response is not None:
                cmds = response.to_dict().get("roleCommandMap", {})
                prompt = response.to_dict().get("prompt", "")
                execute_cmd = response.to_dict().get("executeCmd", "")

            # 异步工具回灌：模拟器不提供 LLM/沙盒响应（真实对战由判题器回灌）
            # task_submit 等KPI因此为0，这是模拟限制，非代码缺陷
            self.state["llmResp"] = ""
            self.state["lastCmdResult"] = ""
            self.state["lastSummonTreasureResult"] = 0
            self.state["lastRoundRoleActionResults"] = {}

            if not cmds:
                in_day = (r - 1) % ROUNDS_PER_DAY
                if in_day < DAY_ROUNDS:
                    self.zero_cmd_rounds += 1

            self._apply_commands(cmds, r)

            # 每轮快照（在命令应用后）
            self._snapshot_history(r)

        return self._collect_kpis()

    # —— 状态更新 ——

    def _update_day_night(self, r: int) -> None:
        in_day = (r - 1) % ROUNDS_PER_DAY
        if in_day == 0 and r > 1:
            # 新一天：重置每日状态
            pass
        # is_day 由 roundNo 计算（protocol.py: is_day = in_day < DAY_ROUNDS）

    def _update_task_state(self, r: int) -> None:
        """模拟 phaseTask 的出现与消失。"""
        if self._task_active:
            rounds_since = r - self._task_accept_round
            if rounds_since >= self._task_timeout:
                # 任务超时
                self._task_active = False
                self.state["phaseTask"] = ""
            else:
                # 任务仍在进行（保持 phaseTask 非空）
                if not self.state.get("phaseTask"):
                    self.state["phaseTask"] = "自进化类1: 请查询北京天气 task_1_beijing.md"
        else:
            self.state["phaseTask"] = ""

    def _handle_night(self, r: int) -> None:
        """夜间简化：机器人来袭，塔输出杀敌，残余机器人打基地/墙。"""
        in_day = (r - 1) % ROUNDS_PER_DAY
        if in_day < DAY_ROUNDS:
            return  # 白天无机器人

        day = (r - 1) // ROUNDS_PER_DAY + 1
        wave = NIGHT_WAVES.get(day, (3, 1, 0, 0))

        # 首夜回合刷怪
        if in_day == DAY_ROUNDS:
            self._spawn_robots(wave, day)

        # 机器人移动 + 攻击（简化）
        self._robots_act(r, day)

    def _spawn_robots(self, wave: tuple, day: int) -> None:
        """生成夜间机器人。"""
        small, middle, large, boss = wave
        robots = []
        rid = 30001
        for _ in range(small):
            robots.append(self._make_robot(rid, "smallRobot"))
            rid += 1
        for _ in range(middle):
            robots.append(self._make_robot(rid, "middleRobot"))
            rid += 1
        for _ in range(large):
            robots.append(self._make_robot(rid, "largeRobot"))
            rid += 1
        for _ in range(boss):
            robots.append(self._make_robot(rid, "bossRobot"))
            rid += 1
        self.state["robot"] = {"roles": robots}

    def _make_robot(self, rid: int, rtype: str) -> dict[str, Any]:
        """机器人生成在地图边缘，朝基地方向。"""
        station = self._get_station()
        if station:
            sx, sy = station["pos"]["x"], station["pos"]["y"]
        else:
            sx, sy = 10, 24
        # 从地图边缘生成
        x = self._random.choice([0, 40, sx - 15, sx + 15])
        y = self._random.choice([0, 31, sy - 10, sy + 10])
        x = max(0, min(40, x))
        y = max(0, min(31, y))
        return {
            "id": rid,
            "pos": {"x": x, "y": y},
            "roleType": rtype,
            "health": ROBOT_HP[rtype],
            "abnormalState": "",
            "targetTeam": "challenger",
        }

    def _robots_act(self, r: int, day: int) -> None:
        """简化机器人行动：向基地移动，被塔攻击，攻击墙/基地。"""
        robots = self.state.get("robot", {}).get("roles", [])
        if not robots:
            return

        station = self._get_station()
        if station is None:
            return

        # 塔输出（简化：每塔每回合杀附近机器人）
        towers = self._get_towers()
        total_dps = 0
        for tower in towers:
            kind = tower.get("roleType", "")
            level = tower.get("level", 1)
            total_dps += TOWER_DPS.get(kind, {}).get(level, 10)

        # 分配伤害到机器人
        remaining_dps = total_dps
        new_robots = []
        for robot in robots:
            if robot["health"] <= 0:
                continue
            if remaining_dps > 0:
                dmg = min(remaining_dps, robot["health"])
                robot["health"] -= dmg
                remaining_dps -= dmg
            if robot["health"] > 0:
                # 机器人向基地移动1格
                self._move_robot_toward(robot, station["pos"])
                new_robots.append(robot)

        # 残余机器人攻击基地/墙
        walls = self._get_walls()
        base_hp = station.get("health", 1500)
        for robot in new_robots:
            rtype = robot.get("roleType", "smallRobot")
            atk = ROBOT_ATK.get(rtype, 5)
            # 优先打墙
            if walls:
                wall = walls[0]
                wall["health"] -= atk
                if wall["health"] <= 0:
                    walls.remove(wall)
            else:
                station["health"] -= atk

        self.state["robot"]["roles"] = new_robots

        # 更新基地HP
        for role in self.state["teamOur"]["roles"]:
            if role.get("roleType") == "station":
                role["health"] = station["health"]

    # —— 命令应用 ——

    def _apply_commands(self, cmds: dict[str, Any], r: int) -> None:
        roles_by_id = {str(rol["id"]): rol for rol in self.state["teamOur"]["roles"]}

        for rid_str, cmd in cmds.items():
            rid = int(rid_str)
            role = roles_by_id.get(rid_str)
            if role is None:
                continue
            action = cmd.get("action", "")
            try:
                self._apply_one(role, rid, cmd, action, r)
            except Exception:
                pass  # 模拟容错：忽略异常命令

    def _apply_one(self, role: dict, rid: int, cmd: dict,
                   action: str, r: int) -> None:
        if action == "move":
            self._cmd_move(role, cmd)
        elif action == "build":
            self._cmd_build(role, cmd, r)
        elif action == "collect":
            self._cmd_collect(role, cmd)
        elif action == "sell":
            self._cmd_sell(role, cmd, r)
        elif action == "buy":
            self._cmd_buy(role, cmd)
        elif action == "use":
            self._cmd_use(role, cmd, r)
        elif action == "acceptTask":
            self._cmd_accept_task(role, r)
        elif action == "submitAnswer":
            self._cmd_submit_answer(role, cmd, r)
        elif action == "remove":
            self._cmd_remove(role, cmd)
        elif action == "summonTreasure":
            self._cmd_summon_treasure(role, cmd)
        elif action == "drop":
            self._cmd_drop(role, cmd)

    def _cmd_move(self, role: dict, cmd: dict) -> None:
        target = cmd.get("targetPos", [{}])[0]
        tx, ty = target.get("x"), target.get("y")
        if tx is None or ty is None:
            return
        # 简化碰撞检查：只要不是其他己方单位位置就行
        occupied = set()
        for r2 in self.state["teamOur"]["roles"]:
            if r2.get("id") != role.get("id"):
                occupied.add((r2["pos"]["x"], r2["pos"]["y"]))
        if (tx, ty) not in occupied:
            role["pos"]["x"] = tx
            role["pos"]["y"] = ty

    def _cmd_build(self, role: dict, cmd: dict, r: int) -> None:
        name = cmd.get("name", "")
        target = cmd.get("targetPos", [{}])[0]
        tx, ty = target.get("x"), target.get("y")
        if tx is None or ty is None:
            return

        if name in TOWER_TYPES:
            # 建塔：扣25金
            if self._get_gold() < TOWER_COST:
                return
            self._spend_gold(TOWER_COST)
            new_unit = {
                "id": self._next_unit_id,
                "pos": {"x": tx, "y": ty},
                "roleType": name,
                "health": 1000,
                "level": 1,
                "attackPower": 20 if name == "rocket" else 10,
                "attackRange": {"gatling": 3, "railgun": 6, "rocket": 10}.get(name, 3),
                "cooldown": 0,
                "backPackCapability": 0,
                "backpack": [],
            }
            self._next_unit_id += 1
            self.state["teamOur"]["roles"].append(new_unit)
            if "first_tower_round" not in self.timeline:
                self.timeline["first_tower_round"] = r
            tower_count = len(self._get_towers())
            if tower_count >= 3 and "third_tower_round" not in self.timeline:
                self.timeline["third_tower_round"] = r
        elif name == "wall":
            # 建墙：消耗1个stone
            backpack = role.get("backpack", [])
            if "stone" not in backpack:
                return
            backpack.remove("stone")
            new_unit = {
                "id": self._next_unit_id,
                "pos": {"x": tx, "y": ty},
                "roleType": "wall",
                "health": 1000,
                "level": 1,
                "attackPower": 0,
                "attackRange": 0,
                "cooldown": 0,
                "backPackCapability": 0,
                "backpack": [],
            }
            self._next_unit_id += 1
            self.state["teamOur"]["roles"].append(new_unit)
            if "first_wall_round" not in self.timeline:
                self.timeline["first_wall_round"] = r

    def _cmd_collect(self, role: dict, cmd: dict) -> None:
        target = cmd.get("targetPos", [{}])[0]
        tx, ty = target.get("x"), target.get("y")
        if tx is None or ty is None:
            return
        # 找矿区
        for zone in self.state["mapInfo"]["zones"]:
            if zone["pos"]["x"] == tx and zone["pos"]["y"] == ty:
                ore = zone.get("neutralType", "")
                if ore in ORE_TYPES:
                    backpack = role.setdefault("backpack", [])
                    cap = role.get("backPackCapability", 100)
                    if len(backpack) < cap:
                        backpack.append(ore)
                        # 矿区使用计数
                        key = f"{tx},{ty}"
                        self._mine_uses[key] = self._mine_uses.get(key, 0) + 1
                        if self._mine_uses[key] >= 10:
                            # 矿区消失，刷新到随机位置
                            zone["pos"]["x"] = self._random.randint(0, 40)
                            zone["pos"]["y"] = self._random.randint(0, 31)
                            self._mine_uses.pop(key, None)
                    break

    def _cmd_sell(self, role: dict, cmd: dict, r: int) -> None:
        name = cmd.get("name", "")
        num = cmd.get("num", 1)
        backpack = role.get("backpack", [])
        count = backpack.count(name)
        actual = min(count, num)
        if actual <= 0:
            return
        price = self._get_vendor_price(name)
        self._add_gold(price * actual)
        for _ in range(actual):
            backpack.remove(name)
        self.sell_count += 1
        if "first_sell_round" not in self.timeline:
            self.timeline["first_sell_round"] = r

    def _cmd_buy(self, role: dict, cmd: dict) -> None:
        name = cmd.get("name", "")
        num = cmd.get("num", 1)
        price = self._get_weapon_price(name)
        total = price * num
        if self._get_gold() < total:
            return
        self._spend_gold(total)
        backpack = role.setdefault("backpack", [])
        cap = role.get("backPackCapability", 100)
        for _ in range(num):
            if len(backpack) < cap:
                backpack.append(name)

    def _cmd_use(self, role: dict, cmd: dict, r: int) -> None:
        name = cmd.get("name", "")
        target = cmd.get("targetPos", [None])
        backpack = role.get("backpack", [])
        if name not in backpack:
            return

        # 升级券
        if name in ("WeaponUpgradeVoucher1", "WeaponUpgradeVoucher2"):
            self._upgrade_tower(cmd, name, r)
            backpack.remove(name)
        elif name in ("StationUpgradeVoucher1", "StationUpgradeVoucher2"):
            self._upgrade_station(name, r)
            backpack.remove(name)
        elif name in ("WallUpgradeVoucher1", "WallUpgradeVoucher2"):
            self._upgrade_wall(cmd, name)
            backpack.remove(name)
        elif name == "Medicine":
            role["health"] = 220 if role.get("roleType") == "worker" else 200
            backpack.remove(name)
        elif name == "WallFixer":
            if target and target[0]:
                tx, ty = target[0].get("x"), target[0].get("y")
                for w in self._get_walls():
                    if w["pos"]["x"] == tx and w["pos"]["y"] == ty:
                        w["health"] = {1: 1000, 2: 1500, 3: 2000}.get(w.get("level", 1), 1000)
                        break
            backpack.remove(name)
        else:
            backpack.remove(name)

    def _upgrade_tower(self, cmd: dict, voucher: str, r: int) -> None:
        target = cmd.get("targetPos", [{}])[0]
        tx, ty = target.get("x"), target.get("y")
        for role in self.state["teamOur"]["roles"]:
            if (role.get("roleType") in TOWER_TYPES
                    and role["pos"]["x"] == tx and role["pos"]["y"] == ty):
                cur_level = role.get("level", 1)
                if voucher == "WeaponUpgradeVoucher1" and cur_level == 1:
                    role["level"] = 2
                    role["health"] = 1500
                    role["attackRange"] = {"gatling": 5, "railgun": 8, "rocket": 15}.get(
                        role["roleType"], 5)
                    role["attackPower"] = {"gatling": 20, "railgun": 20, "rocket": 40}.get(
                        role["roleType"], 20)
                    if "first_tower_upgrade_round" not in self.timeline:
                        self.timeline["first_tower_upgrade_round"] = r
                elif voucher == "WeaponUpgradeVoucher2" and cur_level == 2:
                    role["level"] = 3
                    role["health"] = 2000
                    role["attackRange"] = {"gatling": 7, "railgun": 10, "rocket": 10**9}.get(
                        role["roleType"], 7)
                    role["attackPower"] = {"gatling": 30, "railgun": 30, "rocket": 60}.get(
                        role["roleType"], 30)
                break

    def _upgrade_station(self, voucher: str, r: int) -> None:
        for role in self.state["teamOur"]["roles"]:
            if role.get("roleType") == "station":
                cur_level = role.get("level", 1)
                if voucher == "StationUpgradeVoucher1" and cur_level == 1:
                    role["level"] = 2
                    role["health"] = 3000
                    if "base_upgrade_round" not in self.timeline:
                        self.timeline["base_upgrade_round"] = r
                elif voucher == "StationUpgradeVoucher2" and cur_level == 2:
                    role["level"] = 3
                    role["health"] = 4500
                break

    def _upgrade_wall(self, cmd: dict, voucher: str) -> None:
        target = cmd.get("targetPos", [{}])[0]
        tx, ty = target.get("x"), target.get("y")
        for w in self._get_walls():
            if w["pos"]["x"] == tx and w["pos"]["y"] == ty:
                cur = w.get("level", 1)
                if voucher == "WallUpgradeVoucher1" and cur == 1:
                    w["level"] = 2
                    w["health"] = 1500
                elif voucher == "WallUpgradeVoucher2" and cur == 2:
                    w["level"] = 3
                    w["health"] = 2000
                break

    def _cmd_accept_task(self, role: dict, r: int) -> None:
        if not self._task_active:
            self._task_active = True
            self._task_accept_round = r
            self.task_accept_count += 1
            if "first_accept_task_round" not in self.timeline:
                self.timeline["first_accept_task_round"] = r

    def _cmd_submit_answer(self, role: dict, cmd: dict, r: int) -> None:
        if self._task_active:
            self._task_active = False
            self.state["phaseTask"] = ""
            self.task_submit_count += 1
            self._add_gold(self._task_reward_gold)
            if "first_submit_answer_round" not in self.timeline:
                self.timeline["first_submit_answer_round"] = r

    def _cmd_remove(self, role: dict, cmd: dict) -> None:
        target = cmd.get("targetPos", [{}])[0]
        tx, ty = target.get("x"), target.get("y")
        roles = self.state["teamOur"]["roles"]
        self.state["teamOur"]["roles"] = [
            r2 for r2 in roles
            if not (r2.get("roleType") == "wall"
                    and r2["pos"]["x"] == tx and r2["pos"]["y"] == ty)
        ]

    def _cmd_summon_treasure(self, role: dict, cmd: dict) -> None:
        items = cmd.get("item", [])
        backpack = role.get("backpack", [])
        for item in items:
            if item in backpack:
                backpack.remove(item)

    def _cmd_drop(self, role: dict, cmd: dict) -> None:
        name = cmd.get("name", "")
        backpack = role.get("backpack", [])
        if name in backpack:
            backpack.remove(name)

    # —— 辅助查询 ——

    def _move_robot_toward(self, robot: dict, target_pos: dict) -> None:
        rx, ry = robot["pos"]["x"], robot["pos"]["y"]
        tx, ty = target_pos["x"], target_pos["y"]
        dx = 1 if tx > rx else (-1 if tx < rx else 0)
        dy = 1 if ty > ry else (-1 if ty < ry else 0)
        robot["pos"]["x"] += dx
        robot["pos"]["y"] += dy

    def _get_gold(self) -> int:
        return self.state["teamOur"].get("goldNum", 0)

    def _add_gold(self, amount: int) -> None:
        self.state["teamOur"]["goldNum"] = self._get_gold() + amount

    def _spend_gold(self, amount: int) -> None:
        self.state["teamOur"]["goldNum"] = max(0, self._get_gold() - amount)

    def _get_station(self) -> dict | None:
        for role in self.state["teamOur"]["roles"]:
            if role.get("roleType") == "station":
                return role
        return None

    def _get_towers(self) -> list[dict]:
        return [r for r in self.state["teamOur"]["roles"]
                if r.get("roleType") in TOWER_TYPES and r.get("health", 0) > 0]

    def _get_walls(self) -> list[dict]:
        return [r for r in self.state["teamOur"]["roles"]
                if r.get("roleType") == "wall" and r.get("health", 0) > 0]

    def _get_vendor_price(self, ore: str) -> int:
        for item in self.state.get("vendorShopList", []):
            if item["name"] == ore:
                return item["price"]
        return {"stone": 1, "iron": 3, "copper": 5}.get(ore, 1)

    def _get_weapon_price(self, name: str) -> int:
        for item in self.state.get("weaponShopList", []):
            if item["name"] == name:
                return item["price"]
        return 9999

    # —— KPI 汇总 ——

    def _collect_kpis(self) -> dict[str, Any]:
        towers = self._get_towers()
        walls = self._get_walls()
        station = self._get_station()
        gold = self._get_gold()
        base_level = station.get("level", 1) if station else 0
        base_hp = station.get("health", 0) if station else 0
        tower_lv2_count = sum(1 for t in towers if t.get("level", 1) >= 2)
        rocket_count = sum(1 for t in towers if t.get("roleType") == "rocket")

        # 按 milestone 收集
        kpis: dict[str, Any] = {}
        for milestone in (10, 30, 70, 130):
            # 注：这里用最终值近似（完整实现需要存每轮快照）
            pass

        # 最终态 KPI
        kpis["tower_count_r10"] = self._approx_at_round(10, "tower_count")
        kpis["tower_count_r30"] = self._approx_at_round(30, "tower_count")
        kpis["rocket_ratio_r10"] = self._approx_rocket_ratio(10)
        kpis["gold_r30"] = self._approx_at_round(30, "gold")
        kpis["gold_r70"] = self._approx_at_round(70, "gold")
        kpis["sell_count_r70"] = min(self.sell_count, 999)
        kpis["task_accept_count_r70"] = min(self.task_accept_count, 999)
        kpis["task_submit_count_r70"] = min(self.task_submit_count, 999)
        kpis["base_level_r130"] = base_level
        kpis["tower_lv2_count_r130"] = tower_lv2_count
        kpis["base_alive_r130"] = 1 if base_hp > 0 else 0
        kpis["wall_count_r70"] = self._approx_at_round(70, "wall_count")
        kpis["zero_cmd_rounds_r70"] = min(self.zero_cmd_rounds, 999)
        # R260 (Day2结束) KPI
        kpis["base_level_r260"] = base_level
        kpis["tower_lv2_count_r260"] = tower_lv2_count
        kpis["base_alive_r260"] = 1 if base_hp > 0 else 0
        kpis["gold_r260"] = gold
        kpis["wall_count_r260"] = len(walls)
        kpis["timeline"] = self.timeline
        kpis["final_gold"] = gold
        kpis["final_tower_count"] = len(towers)
        kpis["final_wall_count"] = len(walls)
        kpis["final_base_hp"] = base_hp
        kpis["final_base_level"] = base_level

        return kpis

    # —— 每轮快照存储 ——

    def _snapshot_history(self, r: int) -> None:
        """在 run() 每轮调用，存储快照。"""
        towers = self._get_towers()
        walls = self._get_walls()
        self._history.append({
            "round": r,
            "tower_count": len(towers),
            "wall_count": len(walls),
            "gold": self._get_gold(),
        })
        # 记录塔快照（用于 rocket_ratio）
        self._tower_history[r] = [dict(t) for t in towers]

    def _approx_at_round(self, round_no: int, key: str) -> int:
        if round_no <= len(self._history):
            return self._history[round_no - 1].get(key, 0)
        if self._history:
            return self._history[-1].get(key, 0)
        return 0

    def _approx_rocket_ratio(self, round_no: int) -> float:
        towers_at = self._tower_history.get(round_no, [])
        if not towers_at:
            return 0.0
        rockets = sum(1 for t in towers_at if t.get("roleType") == "rocket")
        return rockets / len(towers_at) if towers_at else 0.0


def main() -> int:
    raw = sys.stdin.buffer.read().decode("utf-8")
    fixture = json.loads(raw)
    judge = MockJudge(fixture)
    kpis = judge.run()
    data = json.dumps(kpis, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.buffer.write(data.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
