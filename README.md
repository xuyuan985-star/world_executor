# WorldExecutor — 崩坏：星穹铁道 全宝箱收集助手

基于 [March7thAssistant](https://github.com/moesnow/March7thAssistant) 思路**数据内化**的宝箱收集系统（功能自研/源码迁入项目内，运行时零依赖外部目录）。全自动：任务中心跑 m7 全套任务（锄大地/体力/模拟宇宙）；宝箱收集走 模板匹配 + 坐标兜底 + 差分验证 + 轨迹录制回放。

## 新电脑启动（5 分钟）

要求：**Windows 10/11 + Python 3.11+**（项目依赖 Windows API：窗口/输入/截图）。

```bash
# 1. 克隆仓库
git clone https://github.com/xuyuan985-star/world_executor.git
cd world_executor

# 2. 创建唯一虚拟环境 m7_venv（Python 3.12+，m7 任务中心要求）并装依赖
py -3.14 -m venv m7_venv       # 或 py -3.13 / -3.12 / python
m7_venv\Scripts\activate       # Windows
pip install -r requirements.txt

# 3. 配置环境变量（无 key 也能启动，VLM 功能会降级）
copy .env.example .env        # Windows
# 然后编辑 .env 填入 QWEN_API_KEY（可跳过，模板匹配路径不需要）

# 4. m7 任务模块（源码在项目内 m7/，gitignore 不入库；子进程执行）
#    缺失时：tools/setup_m7.py 自动准备（克隆官方仓库到 m7/ + 建环境）
#    任务中心 → 更新 m7 模块（外部镜像 git pull + 同步回项目内 m7/）

# 5. 启动 GUI
双击 启动世界执行器.bat（自动提权） 或
m7_venv\Scripts\python.exe -m app
```

> **环境已统一为 `m7_venv`（Python 3.12+）**——GUI 与 m7 任务中心同环境（m7 任务在
> QProcess 子进程独立跑，0.6.0 起不再进程内集成）。旧 `.venv`（3.11）已废弃。
> 所有命令用 `m7_venv\Scripts\python.exe`（不要用系统 `python`，可能缺 PySide6）。
> 真机执行（点击游戏窗口）需要**管理员权限**——启动时按提示确认提权。

## 功能一览

| 入口 | 说明 |
|------|------|
| **指挥台** | 真机执行宝箱任务（模板匹配 + 坐标兜底 + 差分验证 + verify） |
| **任务中心** | m7 全部任务模块子进程执行（日常/体力/锄大地/模拟宇宙/差分/货币战争/挑战），实时日志 + HUD 游戏内浮窗 + 更新 m7 按钮 |
| **世界图** | 地图集展示（真实点位数量来自地图工具核查）+ 区域执行 |
| **观察中心** | 实时游戏画面 + 事件流统计 + 时间线 |
| **设置** | VLM 模型配置 |
| `python tools\run_pipeline.py` | 一键预处理：视频 → 抽帧 → VLM 检测 → 裁剪模板 → 知识包 |
| `python tools\verify_points.py` | 点位核查：网站真实数据 vs 本地地图集（覆盖率报告） |
| `python -m app --selftest` | 启动自检报告 |
| `python -m unittest discover -s tests -p "test_*.py"` | 单测 |

## 宝箱收集运行时策略

- **坐标兜底**：视频帧模板实测匹配不上 → 按知识包归一化坐标点击（宝箱固定点位）
- **差分验证**：点击后画面变化检测 + nudge 微调重试（点偏自动纠）
- **界面归一化**：任务开始前 OCR 检测战斗/弹窗/菜单 → ESC/点按钮退出到可执行画面
- **三大策略**：
  - 遇怪：auto（自动战斗键）或 kill（秒杀角色战技键）→ 等结算
  - 地图未解锁：传送后检测解锁提示 → 明确跳过
  - 机关：检测机关提示词 → 标记 requires_mechanism（轨迹回放路线处理）
- **轨迹录制/回放**：任务中心"录制轨迹"按钮——手动操作一次录制 WASD/视角/点击（归一化坐标，分辨率/全屏自适应）→ 回放复现

## 目录

```
app/             统一入口（python -m app）
config/          环境配置（.env 不入库，模板见 .env.example）
gui/             PySide6 界面（指挥台/任务中心/世界图/观察中心/设置）
runtime/         状态机、orchestrator、执行器、输入后端、轨迹录制回放
ingest/          离线管线：VLM 客户端、视频抽帧、模板裁剪、一键预处理
knowledge/       地图集（guides/maps 展示库）+ 执行包（source）
m7_venv/         唯一环境（Python 3.14——GUI 与 m7 任务共享依赖，不入库）
tools/           门禁/预处理/核查/校准等工具
tests/           分层单测
docs/            企划书与设计文档
```

## 开发铁律

- VLM 只产事件描述/点位，运行时执行链零 VLM（模板匹配驱动）。
- 知识（文件）与状态（runtime.db，SQLite）分离。
- 状态门控：观测 = value + observer + confidence + time。
- 本环境 Qt 跨线程信号不可靠——一律用轮询消费（HUD/HealthWorker/TaskProcess 同款模式）。
