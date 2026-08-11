# R9 测试与门禁审查（2026-08-12）

## 测试体系（tests/ 20 文件 1452 行，26 测试点）

| 目录 | 用例 | 覆盖 |
|---|---|---|
| config_tests | 5 | settings 默认值/reload/validate/redact_secrets/版本单一来源 |
| coords_tests | 7 | 坐标换算 1080p/1440p/4k/DPI125/scale_zero 防护/窗口偏移 |
| gui | 6 | close_pending 3（空闲/运行中/回归）+ runner 生命周期 3（fail-closed/stop 安全/初始态） |
| knowledge_tests | 8 | JSON 损坏分类/重复 id 拒绝/排序稳定/不可达房间/坏 JSON/缺字段/wrong_type/environment 标记 |
| planner/ | 脚本式 | game_launcher/map_transfer/pixel_diff/planner/pos_fallback/ready_state/strategies/trajectory |
| replay/ | 脚本式 | 行为回放回归（事件流→状态机断言） |
| vision/ | 脚本式 | 视觉门 6 cases（mask 匹配/评分门/VLMDead 降级） |

## 门禁 10 步（tools/run_gate.py）

1. **architecture**：tools/architecture_check.py --json（依赖方向 + 环 + 动态导入 + 危险调用）
2. **security**：quarantine sanitize + pylnk3 stub 注入自检
3. **unit checks**：AST 全源码语法（utf-8-sig 容忍 BOM）+ ErrorCode 断言
4. **replay test**：tests/replay/test_action_replay.py
5. **vision gate**：tests/vision/test_gate.py（6 cases）
6. **action guard**：tools/action_guard_test.py
7. **planner**：tests/planner/test_planner.py（4 cases：planned/room_mismatch/already_done/failure memory）
8. **smoke**：tools/smoke_orchestrator.py（交接约定跳过——StarRail 反作弊残留干扰）
9. **pipeline**：tools/full_pipeline_test.py（数据→知识包→校验→dry_run 端到端）
10. **dry_run**：runtime/dry_run.py black_tower_test（知识包逻辑验证）

- 每步 subprocess + cwd 固定仓库根 + PYTHONPATH 注入（Bug 64/65：任意启动目录都稳）
- 失败 → 非零退出 + 尾部 400 字符 detail
- 结果落 reports/gate.json（机器可读，CI 用）

## 测试特点

- unittest 为主 + 少量 pytest 风格（pytest 26 passed 中 6 个来自 pytest 发现）
- 大量"脚本式"测试（直接 python 跑，main 内断言）——run_gate 逐个 subprocess 调用
- 测试依赖 tools/smoke_orchestrator 的 FakeObserver/FakeDriver/FakeVLM（mock 驱动 10 场景）
- 关键回归点：坐标换算（多分辨率/DPI）、知识包损坏防护、GUI 关闭保护、任务生命周期 fail-closed

## 覆盖缺口观察（阶段二验证）

1. **replayer/recorder 无单测**——视角回放核心机制（鼠标事件合并/灵敏度换算）只有实机验证路径，tests/planner/test_trajectory.py 是什么？（看 FakeBackend/FakeGeom——可能只测 orchestrator 层轨迹接线）
2. win32_backend 无单测（真实 API 无法 CI 测——可接受，但 InputResult 语义可测）
3. EventBus 无独立单测（并发/弱引用/轮转）
4. main_window 无单测（依赖 Qt——仅 controller 层可测）
5. task 中心 QProcess 链路无单测（fail-closed 分支有——runner_lifecycle 3 个）
6. tests/vision/test_gate.py 有 6 cases 但 pytest 只发现部分（脚本式 main）——门禁覆盖 OK
