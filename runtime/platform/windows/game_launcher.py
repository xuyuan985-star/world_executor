"""游戏拉起（借鉴 March7th LocalGameController.start_game_process + tasks/game）：

窗口不存在时自动启动游戏：cmd start 启动 exe → 轮询等窗口出现（m7 同款
360s）→ 窗口就绪后尝试点"点击进入"（m7 click_enter.png 资产——游戏启动
后的进入界面按钮）。点进入失败不阻塞（登录态/加载慢——用户手动处理）。

game_path 来源：m7 config.yaml（任务中心与 m7 共用配置）。
"""
import subprocess
import time
from pathlib import Path

from runtime.win_capture import GAME_TITLE, find_game_window


def m7_config_value(key, default=None, m7_root=None):
    """读 m7 config.yaml 任意键（ruamel 保类型；失败返回 default）。"""
    if m7_root is None:
        m7_root = (Path(__file__).resolve().parent.parent.parent.parent.parent
                   / "March7thAssistant")
    cfg_path = Path(m7_root) / "config.yaml"
    if not cfg_path.exists():
        return default
    try:
        import yaml
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return default
    if not isinstance(data, dict):
        return default
    return data.get(key, default)


def game_executable(m7_root=None):
    """m7 config.yaml 的 game_path（本地游戏可执行文件路径）。"""
    if m7_root is None:
        # game_launcher 在 world_executor/runtime/platform/windows/——
        # 上溯 5 级到 Open Code/，m7 是 world_executor 的兄弟目录
        m7_root = (Path(__file__).resolve().parent.parent.parent.parent.parent
                   / "March7thAssistant")
    cfg_path = Path(m7_root) / "config.yaml"
    if not cfg_path.exists():
        return None
    try:
        import yaml
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    path = data.get("game_path") if isinstance(data, dict) else None
    if not path or not Path(str(path)).exists():
        return None
    return str(path)


def launch_game_process(executable):
    """启动游戏 exe（m7 同款：cmd start 带工作目录；失败 Popen 兜底）。"""
    folder = str(Path(executable).parent)
    try:
        code = subprocess.call(
            f'cmd /C start "" /D "{folder}" "{executable}"',
            shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if code == 0:
            return True
    except Exception:
        pass
    try:
        subprocess.Popen(executable, cwd=folder)
        return True
    except Exception:
        return False


def wait_for_game_window(wait_seconds=360, poll_interval=5.0):
    """轮询等游戏窗口出现（find_game_window 可见+非最小化）。"""
    from runtime.win_capture import find_game_window
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        game = find_game_window(GAME_TITLE)
        if game is not None:
            return game
        time.sleep(poll_interval)
    return None


def click_enter_if_present(max_tries=5, interval=10.0):
    """游戏启动后的"点击进入"界面（m7 click_enter.png 资产）——点进入游戏。

    模板匹配全屏（游戏全屏/窗口化均可）；失败不阻塞（登录态/加载慢）。
    返回是否点过。
    """
    m7_assets = (Path(__file__).resolve().parent.parent.parent.parent
                 / "March7thAssistant" / "assets" / "images" / "screen" / "click_enter.png")
    if not m7_assets.exists():
        return False
    from runtime.input.template_backend import TemplateMatcher
    tm = TemplateMatcher(threshold=0.7)
    for _ in range(max_tries):
        try:
            hit = tm.locate(str(m7_assets))
        except Exception:
            return False
        if hit is None:
            return False  # 未出现（可能已进入游戏/未到该界面）——不再等
        _, cx, cy = hit
        try:
            from runtime.input.win32_backend import Win32Backend
            r = Win32Backend().click(cx, cy)
            if r.success:
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def ensure_game_launched(wait_seconds=360, auto_enter=True):
    """总入口：窗口在 → 直接返回 (True, "already_running")；
    不在 → 启动 → 等窗口 → 点进入。失败返回 (False, 原因)。"""
    from runtime.win_capture import find_game_window
    if find_game_window(GAME_TITLE) is not None:
        return True, "already_running"
    exe = game_executable()
    if not exe:
        return False, "game_path 未配置或不存在（m7 config.yaml）"
    if not launch_game_process(exe):
        return False, f"游戏启动失败: {exe}"
    game = wait_for_game_window(wait_seconds=wait_seconds)
    if game is None:
        return False, f"等待游戏窗口超时（{wait_seconds}s）"
    entered = False
    if auto_enter:
        entered = click_enter_if_present()
    return True, ("started" if entered else "started_no_enter")
