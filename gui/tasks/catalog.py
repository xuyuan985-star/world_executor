"""March7th 任务目录：迁移 m7 全部任务模块（子进程模式）。

决策（5 轮复盘敲定）：
- 子进程执行 `m7 的 python main.py <action>`（m7 官方同款模式——GUI 启
  子进程，任务在独立进程跑，cwd/单例/配置零冲突）
- 环境变量 MARCH7TH_DOCKER_STARTED=true：跳过 first_run 检查（本机
  config.yaml auto_update=false 会直接退出）与任务结束 pause（input 等待
  会把子进程挂住）
- 停止 = TerminateProcess（m7 任务为幂等导航，中断安全）
"""

from pathlib import Path

# m7 仓库根（相对本文件：world_executor/gui/tasks -> world_executor -> March7thAssistant）
M7_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "March7thAssistant"
# m7 子进程专用 venv（Python 3.14——m7 官方要求 >=3.12，PEP 701 f-string 语法；
# 本项目主 venv 是 3.11 不够）。依赖 = m7 requirements 除投毒包 pylnk3
# （quarantine stub 已在 launcher 注入）
M7_PYTHON = Path(__file__).resolve().parent.parent.parent / "m7_venv" / "Scripts" / "python.exe"

# 任务分组定义（id 对齐 m7 main.py run_sub_task 的 action 白名单）
TASK_GROUPS = [
    ("日常", [
        ("routine", "日常", "每日实训全套（委托/合成/体力清理组合）"),
        ("daily", "每日实训", "每日任务 + 领取奖励"),
        ("fight", "锄大地", "刷怪清理（战斗循环）"),
        ("redemption", "兑换码", "兑换码批量兑换"),
    ]),
    ("体力", [
        ("power", "清体力", "按 config.yaml 体力计划刷副本"),
    ]),
    ("挑战", [
        ("forgottenhall", "混沌回忆", "忘却之庭挑战"),
        ("purefiction", "虚构叙事", "虚构叙事挑战"),
        ("apocalyptic", "末日幻影", "末日幻影挑战"),
    ]),
    ("周常", [
        ("universe", "模拟宇宙", "模拟宇宙刷取"),
        ("divergent", "差分宇宙", "差分宇宙"),
        ("divergentloop", "差分宇宙·循环", "循环刷取"),
        ("currencywars", "货币战争", "货币战争"),
        ("currencywarsloop", "货币战争·循环", "循环刷取"),
    ]),
    ("工具", [
        ("screen_test", "界面可切换性测试", "检查各界面图可识别"),
    ]),
]

# 扁平任务表：id -> (分组, 名称, 说明)
TASKS = {}
for group, items in TASK_GROUPS:
    for tid, name, desc in items:
        TASKS[tid] = (group, name, desc)


def task_name(task_id):
    entry = TASKS.get(task_id)
    return entry[1] if entry else task_id
