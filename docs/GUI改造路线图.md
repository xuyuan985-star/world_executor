# GUI 修复实施路线图（Phase 0-5）

> 2026-08-08。原则：不推翻重写，按风险顺序止血 → 结构化。
> 190+ 风险点已处置/记录（见变更与问题报告第 56-68 轮）。

---

## Phase 0：止血（✅ 已完成）

| 项 | 轮次 |
|---|---|
| 点开始无反应（cwd 污染根因） | 45 |
| 全局异常捕获（excepthook + gui_error.log） | 59 |
| 页面构造异常隔离（ErrorPage） | 59 |
| closeEvent 完整链（stop runtime → health → unsubscribe） | 59/62 |
| 防重复启动 + 启停按钮矩阵 | 56/57 |
| 跨线程 Qt 操作（信号投递，GUI 线程处理） | 60 |
| QPainter 异常保护 + 布局缓存 | 60/64 |
| EventBus 订阅锁 + unsubscribe | 49/57 |
| 启动/停止/失败状态反馈 | 56/57/63 |
| QSharedMemory 单实例 | 66 |
| 线程命名 + 诊断快照 | 67/68 |

## Phase 1：线程与生命周期（部分完成 ✅ / 规划 🔲）

- ✅ HealthWorker 异常透传 + cwd 恢复
- ✅ Runtime runner stop_event 真停止
- 🔲 Worker 统一生命周期（deleteLater 链）——当前无 moveToThread 长任务，暂不引入
- 🔲 心跳监控（GUI 侧 Worker 健康）——runtime 侧 SessionWatchdog 已有

## Phase 2：Controller 层（部分完成 ✅ / 规划 🔲）

- ✅ MissionController（gui/controllers/，第 62 轮）
- 🔲 GuideController / SettingsController / DebugController——按需新增
- 🔲 Command/Event 分离（StartMissionCommand → MissionStartedEvent）

## Phase 3：StateStore（规划 🔲）

- 单一 MissionState 枚举（GUI 全部映射，替代三套状态）
- GuiState 模型 + ViewModel 层（页面不再直接吃 dict）
- 事件枚举化（GuiEvent 替代字符串散落）

## Phase 4：页面重构（规划 🔲）

- BasePage 接口（activate/deactivate/refresh/shutdown）
- PageManager（懒加载 + 状态保留）
- 页面职责收敛（只 display，不直接调服务）

## Phase 5：性能与工程化（规划 🔲）

- 更新策略统一（state 100ms / logs 500ms / image 200ms）
- LRU/TTL 缓存统一 + 资源预算
- MonitorPanel（内存/QObject/线程/事件队列）
- Replay 机制 + Mock Runtime + tests/gui/
- 配置迁移 / Feature Flag / 安全模式 / 审计日志 / i18n / QSS 主题

---

## 实施优先级（后续轮次按此执行）

```
Phase 1（线程生命周期）→ Phase 2（Controller 补全）→ Phase 3（StateStore）
→ Phase 4（页面重构）→ Phase 5（性能/测试）
```

每个 Phase 改动均保持现有测试（run_gate 9/9 + smoke 14 场景）兼容。
