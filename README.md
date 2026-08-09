# WorldExecutor — 崩坏：星穹铁道 全宝箱收集助手

基于 [March7thAssistant](https://github.com/moesnow/March7thAssistant) 扩展的半自治宝箱收集系统。
半自动化：模板匹配 → 定位宝箱 → 模拟点击开箱；攻略视频 → VLM 识别 → 点位入库。

## 新电脑启动（5 分钟）

要求：**Windows 10/11 + Python 3.11+**（项目依赖 Windows API：窗口/输入/截图）。

```bash
# 1. 克隆仓库
git clone https://github.com/xuyuan985-star/world_executor.git
cd world_executor

# 2. 创建虚拟环境并装依赖
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

# 3. 配置环境变量（无 key 也能启动，VLM 功能会降级）
copy .env.example .env        # Windows
# 然后编辑 .env 填入 QWEN_API_KEY（可跳过，模板匹配路径不需要）

# 4. 启动 GUI
python -m app
# 或双击根目录的 启动世界执行器.bat
```

> **必须使用 `.venv` 的 Python**（`python` 可能指向系统解释器而缺 PySide6）。
> 真机执行（点击游戏窗口）需要**管理员权限**——启动时按提示确认提权。

## 环境自检 / 门禁

```bash
python -m app --selftest      # 启动自检报告（Config/Knowledge/Runtime/Vision）
python tools\run_gate.py      # 全部门禁（lint/单测/视觉门/冒烟/端到端）
python -m unittest discover -s tests -p "test_*.py"
```

## 功能一览

| 入口 | 说明 |
|------|------|
| `python -m app` | GUI（指挥台/攻略体系/观察中心/视频归档/设置） |
| `python -m app --selftest` | 启动自检报告 |
| `python -m app --gate` | 运行门禁 |
| `python tools\run_gate.py` | 全量门禁 |
| `python tools\stress_test.py --rounds 50` | 压力测试 |
| `python tools\full_pipeline_test.py` | 端到端验收（数据→知识包→GUI 冒烟） |
| `python tools\validate_all.py` | 全库完整性扫描 |

## 目录

```
app/             统一入口（python -m app）
config/          环境配置（.env 不入库，模板见 .env.example）
gui/             PySide6 界面（指挥台/攻略/观察中心/工作室/设置）
runtime/         状态机、步骤执行器、orchestrator、输入后端、dry_run
ingest/          离线管线：VLM 客户端、视频抽帧、模板裁剪、知识归档
knowledge/       攻略库（guides/maps 展示 + source 执行包）
tools/           门禁/自检/迁移/清理/压力等工具
tests/           分层单测（config/knowledge/planner/replay/vision）
docs/            企划书与设计文档
```

## 开发铁律

- VLM 只产事件描述/点位，运行时执行链零 VLM（模板匹配驱动）。
- 知识（文件）与状态（runtime.db，SQLite）分离。
- 状态门控：观测 = value + observer + confidence + time。
- 输入点击（SendInput）需要管理员；操作前强制前台锁定。

## 里程碑

- Sprint 0（完成）：最小运行时 + 四黄金测试 + VLM 离线分析
- M0（完成）：视频 → VLM → 点位自动归档（pending_review 复核链）
- M1-A（完成）：真机闭环——截图→模板匹配→点击→验证（黑塔空间站 30 点位）
- M1-B（进行中）：GUI 完整接入真机执行 + 多地图扩展
