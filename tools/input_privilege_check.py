"""输入权限前置检查（Sprint A：G2 门槛前置——启动前明确输入可用性）。

ISSUE-09（UIPI）/ ISSUE-11（UAC 卡死）：不要在运行中"点击失败才发现"。
本工具输出四通道状态 + 终态：

  [input] process integrity : HIGH / LOW      （IsUserAnAdmin）
  [input] game window       : found / missing
  [input] game integrity    : HIGH / LOW      （游戏进程是否管理员完整性）
  [input] health probe      : READY / degrade（check_health input_l0/l1/l2）
  [input] status            : READY / OBSERVE_ONLY / FAIL

用法：python tools/input_privilege_check.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def is_admin():
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def main():
    if os.name != "nt":
        print("[input] status: FAIL (Windows only)")
        return 1
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()

    from runtime.win_capture import find_game_window
    from security.quarantine import install_pylnk3_stub, require_m7_path
    install_pylnk3_stub()
    try:
        from runtime.drivers.march7th.window import ensure_march7th_env
        require_m7_path(ROOT.parent / "March7thAssistant")
        ensure_march7th_env()
    except Exception as e:
        print(f"[input] march7th env: FAIL ({e!r})")
        return 1

    admin = is_admin()
    print(f"[input] process integrity : {'HIGH' if admin else 'LOW'}")

    game = find_game_window()
    if game is None:
        print("[input] game window : missing")
        print("[input] status: FAIL (游戏未启动——请先启动《崩坏：星穹铁道》并进入主菜单)")
        return 1
    print(f"[input] game window : found (hwnd={hex(game.get('hwnd') or 0)})")

    from runtime.win_capture import process_identity
    game_integrity = None
    try:
        pid = process_identity(game["hwnd"])[1]
        if pid:
            import ctypes.wintypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                try:
                    tok = ctypes.wintypes.HANDLE()
                    if ctypes.windll.advapi32.OpenProcessToken(
                            handle, 0x0008, ctypes.byref(tok)):  # TOKEN_QUERY
                        # 审查 P1：TokenIntegrityLevel 返回 TOKEN_MANDATORY_LABEL
                        #（含 PSID 指针，≥8 字节）——4 字节缓冲必 INSUFFICIENT_BUFFER
                        # 且 il.value 恒 0 → 完整性恒判 LOW。用足够缓冲 + 解析 SID 子权威
                        import ctypes
                        class _SID_AND_ATTRIBUTES(ctypes.Structure):
                            _fields_ = [("Sid", ctypes.c_void_p),
                                        ("Attributes", ctypes.c_ulong)]
                        class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
                            _fields_ = [("Label", _SID_AND_ATTRIBUTES)]
                        label = _TOKEN_MANDATORY_LABEL()
                        sz = ctypes.wintypes.DWORD()
                        ctypes.windll.advapi32.GetTokenInformation(
                            tok, 25, ctypes.byref(label),
                            ctypes.sizeof(label), ctypes.byref(sz))
                        # 解析完整性 SID 子权威（0x1000=Low, 0x2000=Medium, 0x3000=High）
                        # SID 布局：Revision(1)+Count(1)+Authority(6)+SubAuthorities[]——偏移 8 起
                        sid = label.Label.Sid
                        if sid:
                            sub_auth = ctypes.cast(
                                ctypes.c_void_p(sid + 8),
                                ctypes.POINTER(ctypes.c_ulong))
                            il = sub_auth[0]
                            game_integrity = il >= 0x3000
                        ctypes.windll.kernel32.CloseHandle(tok)
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass
    print(f"[input] game integrity : {('HIGH' if game_integrity else 'LOW/unknown')}")

    try:
        from runtime.health import check_health
        h = check_health(game_required=False) or {}
        cap = h.get("capability") or {}
        l0, l1, l2 = cap.get("input_l0"), cap.get("input_l1"), cap.get("input_l2")
        print(f"[input] health probe : L0={l0} L1={l1} L2={l2}")
        if not admin or not (l0 and l1):
            print("[input] status: OBSERVE_ONLY (输入被拦——UIPI/非管理员；可观察不可执行)")
            return 2
        print("[input] status: READY")
        return 0
    except Exception as e:
        print(f"[input] health probe: FAIL ({e!r})")
        print("[input] status: OBSERVE_ONLY")
        return 2


if __name__ == "__main__":
    sys.exit(main())
