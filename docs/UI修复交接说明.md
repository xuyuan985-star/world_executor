# WorldExecutor UI 修复交接说明


## 项目简介


**WorldExecutor**：星穹铁道宝箱自动采集辅助（Windows 自动化 Agent）。基于 March7thAssistant 的 OCR/输入能力 + Qwen VLM 视觉识别，从攻略视频自动提取宝箱点位（黑塔空间站 30 条已入库），通过 GUI 指挥执行。


**技术栈**：Python 3.11 / PySide6 6.11 + qfluentwidgets 1.11.2（.venv 内）/ threading + Qt 信号跨线程。


## 运行方式


```bash
cd C:\Users\xuyua\Desktop\Open Code\world_executor
.venv\Scripts\pythonw.exe gui\run.py    # GUI 启动
python tools/run_gate.py                # 回归门禁（9 步，必须全绿）
```


## 核心文件


| 文件 | 职责 |
|---|---|
| `gui/run.py` | 入口（异常钩子/单实例锁/DPI 策略/目标加载） |
| `gui/main_window.py` | 主窗口（页面容器/事件信号链/关闭流程） |
| `gui/pages/base_page.py` | **统一页面框架**（Header+Content+Footer，刚建，多数页面未接入） |
| `gui/pages/command_deck.py` | 指挥台（目标树/开始停止/状态行/观测/健康栏） |
| `gui/pages/guides_view.py` | 攻略体系（已按 BasePage 重构：Splitter 树+详情+执行按钮） |
| `gui/pages/placeholder.py` | 观测/视频/设置等页面（部分占位，最近在改） |


## 当前 UI 状态（用户截图反馈已确认的问题）


**根因**：不是控件 bug，是**页面框架缺失**——每个页面自己堆 QVBoxLayout，风格漂移、顶部空洞。

已修（第一轮视觉）：
- ✅ 占位页顶部 50% 空洞（addStretch 位置错误）
- ✅ 指挥台：观测 60%/队列 40%、运行状态行、截图占位、健康栏折叠
- ✅ 攻略页：BasePage 框架 + Splitter（树 40%/详情 60%）+ 业务化树（地图→区域→点位带进度）+ "执行此区域"按钮
- ✅ 设置页保存按钮右下固定宽
- ✅ 视频页首屏统计
- ✅ 观测页事件计数统计
- ✅ 全局中文汉化（无英文残留）、砍掉状态机横向线性图


**待修（第二轮，你的任务）**：
1. **全部页面接入 BasePage**（目前只有攻略页用了；观测/视频/设置仍自布局）
2. 视频页**卡片化**（现在是列表像资源管理器——建议名称/大小/操作列或卡片网格）
3. 攻略页详情增强（完成数/定位/标记完成按钮）
4. 指挥台 CommandDeck 也套 BasePage（当前仍自布局）
5. 颜色层级（Fluent 三级：背景/卡片/重点色）+ 字体层级（标题 18/模块 14/内容 12）
6. 左侧导航栏宽度收敛（56~64px）
7. 统一 margin/spacing


## 硬约束

- 不破坏 `python tools/run_gate.py`（9 步全绿）
- 不破坏 smoke 14 场景
- 中文界面
- 用 qfluentwidgets 组件（CardWidget/ComboBox/PrimaryPushButton 等）
- 修改后自查：`python tools/run_gate.py` 通过 + GUI 截图确认


## 业务背景（改 UI 时参考）


- 目标 = 攻略存档点位（`knowledge/guides/maps/02_herta_space_station/points/chests.json` 30 条，地图→区域→点位三层）
- 执行链：MissionController → RuntimeAPI → orchestrator → dry_run/real
- 事件流：EventBus → MainWindow 信号 → GUI 线程槽（跨线程安全链已就位）
