# AGENTS.md

> 本文件供 AI 协作 agent 阅读，记录项目结构、命令与开发约定。

## 项目概述

云核心网编程大赛《未来战争》v1.0 参赛 AI。HTTP-Server 模式：判题器每回合 POST 地图状态 JSON，选手程序返回动作指令 JSON。Python 3.11+ 纯标准库，零第三方依赖。

## 目录结构

```
Competition/
├── CoreGeek/              ← 唯一提交目录（打包此目录）
│   ├── run.sh             bash run.sh port → exec python3 main3.py port
│   ├── main3.py           入口
│   ├── pyproject.toml     requires-python>=3.11
│   └── src/agent/         14 模块
│       ├── server.py      HTTP 入口 + 异常兜底空响应
│       ├── protocol.py    数据模型(13字段解析 + 12命令 + Response)
│       ├── memory.py      跨回合记忆 + pending 异步配对 + LLM配额 + 并发锁
│       ├── brain.py       watchdog(4.5s) + 昼/夜分流 + 优先级裁决
│       ├── economy.py     卖/买/升级链 + 价格推理 + 采集倾斜
│       ├── builder.py     武器选型 + 双层围墙
│       ├── combat.py      BOSS优先 + 加特林锥形/电磁穿透/火箭溅射 + 道具AOE
│       ├── evolver.py     自进化任务状态机(沙盒+LLM+SOP)
│       ├── treasure.py    长上下文宝藏(LLM推断+召唤迭代)
│       ├── adversary.py   召唤令骚扰
│       ├── util.py        弹道/锥形几何
│       └── grid.py        A*寻路 + next_step_to_adjacent
├── scripts/               ← 测试脚本(sys.path 指向 CoreGeek/src)
│   ├── replay.py          全 fixture 回放验证
│   ├── benchmark.py       多回合KPI基准测试(止血闸门，score评估)
│   ├── _bench_worker.py   基准测试子进程(模拟260回合)
│   ├── snapshot.py        行为快照回归(止血)
│   ├── gen_fixtures.py    生成 22 个测试场景
│   └── validate_m2~m8.py  各里程碑专项验收
├── tests/fixtures/        22 个 request 场景 JSON
├── tests/bench_baseline/  KPI基线(对比防退化)
├── docs/                  任务书/接口文档/方案设计
└── Demo/                  原始 demo 参考
```

## 常用命令

```bash
# 运行（判题器调用方式）
bash CoreGeek/run.sh <port>
# 或本地直接跑
py -3.11 CoreGeek/main3.py 6666

# 全量回放验证（必须全 [ALL PASS]）
py -3.11 scripts/replay.py

# 多回合KPI基准测试（止血闸门，score评估）
py -3.11 scripts/benchmark.py            # check：对比基线，有退化 → 退出码 1
py -3.11 scripts/benchmark.py --update   # 重建基线（预期变化时手动跑）

# 行为快照回归（止血，replay 之前先跑）
py -3.11 scripts/snapshot.py            # check：对比基线，有变化 → 退出码 1
py -3.11 scripts/snapshot.py --update   # 仅当变化是预期时，重建基线并提交

# 各里程碑专项验收
py -3.11 scripts/validate_m3.py   # M3 夜间战斗
py -3.11 scripts/validate_m4.py   # M4 价格推理
py -3.11 scripts/validate_m5.py   # M5 自进化任务
py -3.11 scripts/validate_m6.py   # M6 宝藏
py -3.11 scripts/validate_m7.py   # M7 对抗
py -3.11 scripts/validate_m8.py   # M8 边界+回归

# 重新生成 fixture
py -3.11 scripts/gen_fixtures.py

# 重新打包提交物（每次优化后必须执行）
tar -czf CoreGeek.tar.gz CoreGeek
```

## 开发约定（必须遵守）

1. **每次完成优化后必须重新打包 `CoreGeek.tar.gz`**（`tar -czf CoreGeek.tar.gz CoreGeek`），并验证包能解压启动。
2. **代码改动后先跑 `snapshot.py`（止血）→ 再跑 `replay.py` + 相关 `validate_mX.py`**，确认不破坏既有里程碑，再打包。`snapshot.py` 报 CHANGED 时，预期变化则 `--update` 基线并随代码提交；非预期（牵连了无关 fixture）则必须复盘，这是终结“越优化越差”的关键闸门。
3. `CoreGeek/` 是唯一提交目录；根目录无 src/（已删），测试脚本 `sys.path` 指向 `CoreGeek/src`，即测试的就是提交代码。
4. 提交包零依赖纯标准库，判题器环境无需 pip install。

## 关键约束（防再次踩坑）

- **寻路到障碍点必失败**：`grid.next_step` 的 A\* 把目标格当障碍过滤（`if step in blocked`）。矿区/任务点/小贩/武器商店/宝藏点都是 `neutralType`（非 land，是障碍）。**寻路到这些点必须用 `next_step_to_adjacent`**（寻路到障碍旁的可站立邻居），不能用 `next_step(turn, role, 障碍点)`。历史教训：直接寻路到障碍点导致角色全程停摆(0 cmds)惨败。
- **5 秒响应时限**：`brain.decide` 有 watchdog(4.5s) 超时熔断，宁返回部分 cmds 也不超时。
- **5 次异常即退赛**：全程 try/except + 空响应兜底（`server.py` 返回合法三字段空响应）。
- **异步工具 1 回合延迟**：`prompt`→下回合 `llmResp`、`executeCmd`→下回合 `lastCmdResult`，用 `memory.pending_*` 配对，不能同步阻塞。
- **任务期开拓者不移动**（B2）：开拓者接取任务后固定在任务点旁，只 submitAnswer/不动。
- **LLM 配额**：每游戏日 3 次（任务期不计限），`errorCode=5` 时降级纯沙盒。
- **就近配对**：`brain._tower_pairs` 按距离贪心配角色-武器，非 zip 顺序。

## 已知问题与改进方向

- 真实对战日志显示角色曾全程停摆 → 已修 `next_step_to_adjacent`，需对战验证。
- `tower_sites` 仅搜 distance1，若基地旁无可建格可能空 → 待扩大到 distance2。
- `server.py` 日志需增强：记录命令详情 + 地图摘要 + 0-cmd 标记，便于事后追溯。
