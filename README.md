# WorldExecutor — 崩坏：星穹铁道 全宝箱收集助手

基于 [March7thAssistant](https://github.com/moesnow/March7thAssistant) 插件方式扩展的半自治宝箱收集系统。

## 架构（v0.8.1 冻结）

三层分离：

- **知识包**（`knowledge/`）：纯文件，Git 友好。房间图、传送门、地标、宝箱、workflow 步骤序列，协议 v1.3。
- **运行时引擎**（`runtime/`）：March7thAssistant 插件。状态机驱动（Room State Graph + Portal System），运行时零 VLM。
- **预处理管线**（`ingest/`）：离线。攻略视频 → VLM 事件描述 → 知识包（validator 先行，compiler 延至 M0）。

设计铁律：

- VLM 只产事件描述，不产步骤；运行时完全不调用 VLM。
- 知识（文件）与状态（runtime.db）分离，DB 只存执行状态、观测、统计。
- 状态门控：观测 = value + observer + confidence + time。
- Portal fail policy: retry_interact → adjust_position → reacquire_heading → abort。

## 目录

```
config/           环境配置（.env 不入库，key 见本地 .env）
ingest/           离线管线：VLM 客户端、视频抽帧、模板裁剪、知识包校验/编译
runtime/          状态机、步骤执行器、dry_run、DB（runtime.db 不入库）
modules/          三月七插件集成层（M0）
knowledge/        知识包（black_tower_test 为 Sprint 0 测试包）
smoke_test.py     March7thAssistant 能力冒烟
docs/             企划书（v0.4 ~ v0.8.1）
```

## 快速开始

```bash
# 1. 配置 .env（复制 .env.example 填 key）
# 2. 校验知识包
python -m ingest.compiler.validate_graph knowledge/black_tower_test
# 3. 干跑（不依赖游戏）
python runtime/dry_run.py knowledge/black_tower_test
# 4. 上游能力冒烟（需游戏可截图）
python smoke_test.py
```

## Sprint 0 四黄金测试

| 用例 | 场景 |
|------|------|
| A | 普通宝箱，同房间直达 |
| B | 跨 Portal（加载过渡）宝箱 |
| C | 状态门控目标（先触发状态再交互） |
| D | 异常恢复（模板丢失 → 恢复 → 重试） |

## 里程碑

- Sprint 0（当前）：最小运行时 + 四黄金测试 + VLM 离线分析可用
- M0：知识编译器（事件 → 知识包）跑通 9P 测试视频
- M1：真机验证黑塔空间站收容舱段
- M2：通用化与新地图扩展
