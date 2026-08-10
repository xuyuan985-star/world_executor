"""March7th 窗口桥接：可见窗口枚举 + 客户区信息。

March7th 自带的 get_window 取第一个 title 匹配（双实例会踩中隐藏 0x0 窗口），
这里用可见窗口枚举 + 最大客户区选择规避。
"""
import ctypes
import sys
import time
from pathlib import Path

M7_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent / "March7thAssistant"


def find_game_window():
    """窗口查找（统一实现见 runtime/win_capture——客户区+进程名过滤更强）。"""
    from runtime.win_capture import find_game_window as _fg
    return _fg()


def set_foreground_with_retry(hwnd, attempts=3):
    """前台激活（统一实现见 runtime/win_capture——m7 参考三级回退）。"""
    from runtime.win_capture import set_foreground_with_retry as _sf
    return _sf(hwnd)


def ensure_march7th_env():
    """March7th 硬约束：cwd 必须为根目录（CONFIG_PATH=./config.yaml）。

    同时注入 pylnk3 stub（runtime.security 单一实现）：pylnk3 是 PyPI 历史
    投毒包（0.4.2 恶意版本事件），本项目不启动游戏、不用 .lnk 解析，
    禁止装真包（ISSUE-03；payload 已解码审计，见 runtime/security.py）。
    """
    from security.quarantine import install_pylnk3_stub, require_m7_path
    install_pylnk3_stub()
    require_m7_path(M7_ROOT)  # #18-2.4：路径注入前校验结构
    if str(M7_ROOT) not in sys.path:
        sys.path.insert(0, str(M7_ROOT))
    import os
    if os.getcwd() != str(M7_ROOT):
        os.chdir(M7_ROOT)
