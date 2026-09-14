from dataclasses import dataclass, field
from typing import Any

# —— 时间常量 ——
DAY_ROUNDS = 70
NIGHT_ROUNDS = 60
ROUNDS_PER_DAY = DAY_ROUNDS + NIGHT_ROUNDS

# —— 经济/建造常量 ——
WEAPON_BUILD_COST = 25
WALL_MATERIAL = "stone"
LAND = "land"
STATION = "station"
WALL = "wall"
WORKER = "worker"
PIONEER = "pioneer"
TOWER_TYPES = ("gatling", "railgun", "rocket")
CONTROLLABLE_TYPES = (WORKER, PIONEER)
TOWER_RANGE_BY_LEVEL = {
    "gatling": (3, 5, 7),
    "railgun": (6, 8, 10),
    "rocket": (10, 15, 10**9),
}
ROBOT_SCORE = {
    "smallRobot": 1,
    "middleRobot": 2,
    "largeRobot": 4,
    "bossRobot": 10,
}
ROBOT_HEALTH = {
    "smallRobot": 40,
    "middleRobot": 60,
    "largeRobot": 500,
    "bossRobot": 800,
}
# 矿石种类
ORE_TYPES = ("stone", "iron", "copper")
# 阵营
CHALLENGER = "challenger"
DEFENDER = "defender"
# 任务用品（武器商店售卖，用于召唤宝藏）
TASK_ITEMS = (
    "AcientTablet", "StarSand", "FlameBreath",
    "FrostPotion", "ThornAmulet", "IronWhistle",
)
# 召唤宝藏结果码
SUMMON_NO_ATTEMPT = 0
SUMMON_SUCCESS = 1
SUMMON_NO_TREASURE = 2
SUMMON_WRONG_ITEM = 3
SUMMON_TREASURE_EMPTY = 4
# 错误码
ERR_UNKNOWN = 0
ERR_TASK_TIMEOUT = 1
ERR_ANSWER_WRONG = 2
ERR_NETWORK = 3
ERR_CMD_INVALID = 4
ERR_LLM_LIMIT = 5


@dataclass(frozen=True, slots=True)
class Pos:
    x: int
    y: int

    @classmethod
    def load(cls, raw: Any) -> "Pos":
        return cls(int(raw["x"]), int(raw["y"]))

    def dump(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}


def distance(first: Pos, second: Pos) -> int:
    return max(abs(first.x - second.x), abs(first.y - second.y))


def station_footprint(pos: Pos) -> tuple[Pos, ...]:
    return (
        pos,
        Pos(pos.x + 1, pos.y),
        Pos(pos.x, pos.y - 1),
        Pos(pos.x + 1, pos.y - 1),
    )


@dataclass(frozen=True, slots=True)
class Unit:
    unit_id: int
    pos: Pos
    kind: str
    health: int
    level: int
    cooldown: int
    attack_range: int
    attack_power: int
    capacity: int | None
    backpack: tuple[str, ...]

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Unit":
        raw_capacity = raw.get("backPackCapability")
        return cls(
            int(raw.get("id") or 0),
            Pos.load(raw["pos"]),
            str(raw["roleType"]),
            int(raw.get("health") or 0),
            int(raw.get("level") or 0),
            int(raw.get("cooldown") or 0),
            int(raw.get("attackRange") or 0),
            int(raw.get("attackPower") or 0),
            int(raw_capacity) if raw_capacity is not None else None,
            tuple(str(item) for item in raw.get("backpack") or ()),
        )

    @property
    def backpack_full(self) -> bool:
        if self.capacity is None:
            return False
        return len(self.backpack) >= self.capacity

    def has_item(self, name: str) -> bool:
        return name in self.backpack

    def item_count(self, name: str) -> int:
        return self.backpack.count(name)

    def range_of_attack(self) -> int:
        if self.attack_range > 0:
            return self.attack_range
        table = TOWER_RANGE_BY_LEVEL.get(self.kind)
        if table is None:
            return 0
        level = min(max(self.level, 1), len(table))
        return table[level - 1]

    def max_targets(self) -> int:
        # 加特林/火箭随等级多目标；电磁炮恒为1
        if self.kind in ("gatling", "rocket"):
            return min(max(self.level, 1), 3)
        return 1


@dataclass(frozen=True, slots=True)
class Robot:
    robot_id: int
    pos: Pos
    health: int
    role_type: str
    abnormal_state: str
    target_team: str

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Robot":
        return cls(
            int(raw["id"]),
            Pos.load(raw["pos"]),
            int(raw.get("health") or 0),
            str(raw.get("roleType") or ""),
            str(raw.get("abnormalState") or ""),
            str(raw.get("targetTeam") or ""),
        )

    @property
    def is_dizzy(self) -> bool:
        return self.abnormal_state == "dizzy"

    @property
    def score(self) -> int:
        return ROBOT_SCORE.get(self.role_type, 0)

    @property
    def max_health(self) -> int:
        return ROBOT_HEALTH.get(self.role_type, 0)


@dataclass(frozen=True, slots=True)
class PlayerTask:
    task_type: str
    task_position: Pos
    cold_down_rounds: int
    score_reward: int
    gold_reward: int
    is_valid: bool
    timeout_rounds: int

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "PlayerTask":
        return cls(
            str(raw.get("taskType") or ""),
            Pos.load(raw["taskPosition"]),
            int(raw.get("coldDownRounds") or 0),
            int(raw.get("scoreReward") or 0),
            int(raw.get("goldReward") or 0),
            bool(raw.get("isValid") or False),
            int(raw.get("timeoutRounds") or 0),
        )

    @property
    def can_accept(self) -> bool:
        return self.is_valid and self.cold_down_rounds == 0


@dataclass(frozen=True, slots=True)
class WorldNews:
    official_news: str
    folk_legends: str

    @classmethod
    def load(cls, raw: dict[str, Any] | None) -> "WorldNews":
        raw = raw or {}
        return cls(
            str(raw.get("officialNews") or ""),
            str(raw.get("folkLegends") or ""),
        )


@dataclass(frozen=True, slots=True)
class ShopItem:
    name: str
    price: int

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "ShopItem":
        return cls(str(raw.get("name") or ""), int(raw.get("price") or 0))


@dataclass(frozen=True, slots=True)
class ErrorEntry:
    error_code: int
    description: str

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "ErrorEntry":
        return cls(int(raw.get("errorCode") or 0), str(raw.get("description") or ""))


@dataclass(frozen=True, slots=True)
class Turn:
    round_no: int
    day: int
    is_day: bool
    is_new_day: bool
    team_type: str
    team_id: str
    team_name: str
    gold: int
    total_score: int
    width: int
    height: int
    zones: dict[Pos, str]
    ours: tuple[Unit, ...]
    enemies: tuple[Unit, ...]
    robots: tuple[Robot, ...]
    phase_task: str
    last_action_results: dict[int, bool]
    last_summon_result: int
    llm_resp: str
    world_news: WorldNews
    last_cmd_result: str
    vendor_shop: tuple[ShopItem, ...]
    weapon_shop: tuple[ShopItem, ...]
    player_tasks: tuple[PlayerTask, ...]
    errors: tuple[ErrorEntry, ...]

    @classmethod
    def load(cls, payload: dict[str, Any]) -> "Turn":
        round_no = int(payload.get("roundNo") or 1)
        info = payload.get("mapInfo") or {}
        team = payload.get("teamOur") or {}
        enemy = payload.get("teamEnemy") or {}
        robot_block = payload.get("robot") or {}
        day = (round_no - 1) // ROUNDS_PER_DAY + 1
        in_day = (round_no - 1) % ROUNDS_PER_DAY
        return cls(
            round_no=round_no,
            day=day,
            is_day=in_day < DAY_ROUNDS,
            is_new_day=in_day == 0,
            team_type=str(team.get("type") or ""),
            team_id=str(team.get("teamId") or ""),
            team_name=str(team.get("teamName") or ""),
            gold=int(team.get("goldNum") or 0),
            total_score=int(team.get("totalScore") or 0),
            width=int(info.get("width") or 0),
            height=int(info.get("height") or 0),
            zones={
                Pos.load(zone["pos"]): str(zone["neutralType"])
                for zone in info.get("zones") or ()
            },
            ours=tuple(Unit.load(role) for role in team.get("roles") or ()),
            enemies=tuple(Unit.load(role) for role in enemy.get("roles") or ()),
            robots=tuple(
                Robot.load(robot)
                for robot in robot_block.get("roles") or ()
            ),
            phase_task=str(payload.get("phaseTask") or ""),
            last_action_results={
                int(k): bool(v)
                for k, v in (payload.get("lastRoundRoleActionResults") or {}).items()
            },
            last_summon_result=int(payload.get("lastSummonTreasureResult") or 0),
            llm_resp=str(payload.get("llmResp") or ""),
            world_news=WorldNews.load(payload.get("worldNews")),
            last_cmd_result=str(payload.get("lastCmdResult") or ""),
            vendor_shop=tuple(
                ShopItem.load(item) for item in (payload.get("vendorShopList") or ())
            ),
            weapon_shop=tuple(
                ShopItem.load(item) for item in (payload.get("weaponShopList") or ())
            ),
            player_tasks=tuple(
                PlayerTask.load(task) for task in (team.get("playerTasks") or ())
            ),
            errors=tuple(
                ErrorEntry.load(err) for err in (payload.get("errors") or ())
            ),
        )

    # —— 我方单位查询 ——
    def station(self) -> Unit | None:
        for unit in self.ours:
            if unit.kind == STATION and unit.health > 0:
                return unit
        for unit in self.ours:
            if unit.kind == STATION:
                return unit
        return None

    def alive(self, kinds: tuple[str, ...]) -> tuple[Unit, ...]:
        return tuple(
            unit for unit in self.ours
            if unit.kind in kinds and unit.health > 0
        )

    def controllable(self) -> tuple[Unit, ...]:
        return tuple(sorted(
            self.alive(CONTROLLABLE_TYPES), key=lambda unit: unit.unit_id,
        ))

    def workers(self) -> tuple[Unit, ...]:
        return tuple(sorted(
            self.alive((WORKER,)), key=lambda unit: unit.unit_id,
        ))

    def pioneers(self) -> tuple[Unit, ...]:
        return tuple(sorted(
            self.alive((PIONEER,)), key=lambda unit: unit.unit_id,
        ))

    def pioneer(self) -> Unit | None:
        heroes = self.pioneers()
        return heroes[0] if heroes else None

    def weapons(self) -> tuple[Unit, ...]:
        return tuple(sorted(
            self.alive(TOWER_TYPES), key=lambda unit: (unit.pos.x, unit.pos.y),
        ))

    def walls(self) -> tuple[Unit, ...]:
        return self.alive((WALL,))

    def unit_by_id(self, unit_id: int) -> Unit | None:
        for unit in self.ours:
            if unit.unit_id == unit_id:
                return unit
        return None

    def weapon_by_id(self, unit_id: int) -> Unit | None:
        for unit in self.weapons():
            if unit.unit_id == unit_id:
                return unit
        return None

    # —— 矿区/中立查询 ——
    def mines(self, ore_type: str | None = None) -> tuple[Pos, ...]:
        if ore_type is None:
            return tuple(
                pos for pos, kind in self.zones.items()
                if kind in ORE_TYPES
            )
        return tuple(
            pos for pos, kind in self.zones.items() if kind == ore_type
        )

    def stone_mines(self) -> tuple[Pos, ...]:
        return self.mines(WALL_MATERIAL)

    def iron_mines(self) -> tuple[Pos, ...]:
        return self.mines("iron")

    def copper_mines(self) -> tuple[Pos, ...]:
        return self.mines("copper")

    def vendor_pos(self) -> Pos | None:
        for pos, kind in self.zones.items():
            if kind == "vendor":
                return pos
        return None

    def weapon_shop_pos(self) -> Pos | None:
        for pos, kind in self.zones.items():
            if kind == "weaponShop":
                return pos
        return None

    def task_points(self) -> tuple[tuple[str, Pos], ...]:
        prefix = self.team_type
        result = []
        for pos, kind in self.zones.items():
            if kind.startswith(prefix) and "TaskPoint" in kind:
                result.append((kind, pos))
        return tuple(result)

    # —— 商店价格查询 ——
    def vendor_price(self, ore: str) -> int:
        for item in self.vendor_shop:
            if item.name == ore:
                return item.price
        return 0

    def weapon_price(self, name: str) -> int:
        for item in self.weapon_shop:
            if item.name == name:
                return item.price
        return 0

    def has_error(self, code: int) -> bool:
        return any(err.error_code == code for err in self.errors)

    # —— 几何/碰撞 ——
    def footprint(self, unit: Unit) -> tuple[Pos, ...]:
        if unit.kind == STATION:
            return station_footprint(unit.pos)
        return (unit.pos,)

    def land(self, pos: Pos) -> bool:
        if not 0 <= pos.x < self.width or not 0 <= pos.y < self.height:
            return False
        return self.zones.get(pos, LAND) == LAND

    def occupied_cells(self) -> frozenset[Pos]:
        cells: set[Pos] = set()
        for unit in self.ours:
            cells.update(self.footprint(unit))
        return frozenset(cells)

    def blocked(self, moving: Unit) -> frozenset[Pos]:
        cells = {pos for pos, kind in self.zones.items() if kind != LAND}
        cells.update(self.occupied_cells())
        cells.discard(moving.pos)
        for robot in self.robots:
            cells.add(robot.pos)
        return frozenset(cells)

    def in_attack_range(self, weapon: Unit, target: Pos) -> bool:
        return distance(weapon.pos, target) <= weapon.range_of_attack()

    def adjacent(self, a: Pos, b: Pos) -> bool:
        return distance(a, b) <= 1


@dataclass(frozen=True, slots=True)
class Response:
    role_command_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    prompt: str = ""
    execute_cmd: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "roleCommandMap": self.role_command_map,
            "prompt": self.prompt,
            "executeCmd": self.execute_cmd,
        }


# —— 命令构造函数全集 ——
def move_command(pos: Pos) -> dict[str, Any]:
    return {"action": "move", "targetPos": [pos.dump()]}


def attack_command(controller_id: int, targets: Pos | list[Pos]) -> dict[str, Any]:
    if isinstance(targets, Pos):
        pos_list = [targets.dump()]
    else:
        pos_list = [pos.dump() for pos in targets]
    return {
        "action": "attack",
        "targetPos": pos_list,
        "controllerId": str(controller_id),
    }


def sell_command(name: str, num: int = 1) -> dict[str, Any]:
    return {"action": "sell", "name": name, "num": num}


def buy_command(name: str, num: int = 1) -> dict[str, Any]:
    return {"action": "buy", "name": name, "num": num}


def build_command(pos: Pos, name: str) -> dict[str, Any]:
    return {"action": "build", "targetPos": [pos.dump()], "name": name}


def remove_command(pos: Pos) -> dict[str, Any]:
    return {"action": "remove", "targetPos": [pos.dump()]}


def accept_task_command() -> dict[str, Any]:
    return {"action": "acceptTask"}


def submit_answer_command(task_answer: str) -> dict[str, Any]:
    return {"action": "submitAnswer", "taskAnswer": task_answer}


def summon_treasure_command(target: Pos, items: list[str]) -> dict[str, Any]:
    return {
        "action": "summonTreasure",
        "targetPos": [target.dump()],
        "item": items,
    }


def use_command(name: str, target: Pos | None = None) -> dict[str, Any]:
    cmd: dict[str, Any] = {"action": "use", "name": name}
    if target is not None:
        cmd["targetPos"] = [target.dump()]
    return cmd


def drop_command(name: str) -> dict[str, Any]:
    return {"action": "drop", "name": name}


def collect_command(pos: Pos) -> dict[str, Any]:
    return {"action": "collect", "targetPos": [pos.dump()]}
