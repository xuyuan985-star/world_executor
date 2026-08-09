"""M1-A 真机闭环：orchestrator 跑单点 workflow（管理员下）。

模板匹配点击（无 VLM）→ verify 模板消失 → 目标完成。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LOG = ROOT / "logs" / "live_mission.log"
POINT = "herta_space_station_base_zone_0006_87d3"


def _log(m):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(m + "\n")
    print(m)


def main():
    try:
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            _log("[提权] 需要管理员（本机 UAC=直接提升）")
            import pyuac
            pyuac.runAsAdmin()
            sys.exit(0)
        return _run()  # 审查 P1：透传 _run 退出码（失败=1）
    except Exception:
        import traceback
        _log("EXC: " + traceback.format_exc())
        return 1  # 审查 P1：异常路径也要非零退出码


def _restore_game_window():
    """游戏窗口最小化时 find_game_window 找不到（IsIconic 过滤）——先恢复。"""
    import ctypes
    import time
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "崩坏：星穹铁道")
    if not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.5)
    return True


def _run():
    from runtime.events.bus import EventBus
    from runtime.knowledge_loader import KnowledgePackage
    from runtime.orchestrator import WorkflowOrchestrator
    from runtime.state_machine import State

    _log("=== M1-A 真机单点闭环 ===")
    if _restore_game_window():
        _log("[ok] 游戏窗口已恢复（最小化）")
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(str(ROOT / "knowledge" / "source" / "black_tower_test"))
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="live-m1a",
                                use_vlm=False, natural_mode=False)
    _log(f"[ok] orchestrator 就绪，目标 {POINT}")

    results, completed = orch.run_mission([POINT])
    _log(f"[RESULT] results={results} completed={completed}")
    _log(f"[RESULT] state={orch._machine.state.name}")
    for t, ctx in seen:
        if t in ("fail_recorded", "target_progress"):
            _log(f"  {t}: {ctx}")
    if completed == [POINT]:
        _log("[PASS] M1-A 单点闭环成功（点击+验证通过）")
        return 0
    # 审查 P1：失败必须非零退出码（脚本恒 0 无信号价值）
    _log("[FAIL] 未完成——看上方事件")
    return 1


if __name__ == "__main__":
    sys.exit(main())
