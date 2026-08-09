"""统一入口（Bug 202）：python -m app —— 所有启动方式收敛于此。

    python -m app                  # GUI 启动
    python -m app --gate           # 运行门禁
    python -m app --selftest       # 启动自检报告
"""
import sys

from config.version import APP_VERSION


def _check_python_version():
    # Bug 203：Python 版本门槛（3.11+）
    if sys.version_info < (3, 11):
        raise RuntimeError(
            f"需要 Python 3.11+（当前 {sys.version_info.major}.{sys.version_info.minor}）")


def _check_venv():
    # Bug 205：虚拟环境检测（系统 Python 缺依赖风险提示）
    import os
    in_venv = sys.prefix != sys.base_prefix
    if not in_venv and os.name == "nt":
        print(f"[warn] 未检测到虚拟环境（当前: {sys.prefix}）"
              "——建议 .venv\\Scripts\\activate 后运行")
    return in_venv


def selftest():
    """Bug 195：启动自检报告（Config/Knowledge/Runtime/Vision）。"""
    from pathlib import Path
    ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(ROOT))
    print(f"WorldExecutor v{APP_VERSION} 自检报告")
    try:
        from config.settings import validate_config
        ok, problems = validate_config()
        print(f"  Config {'OK' if ok else 'FAIL'}"
              + (f"（{problems}）" if problems else ""))
    except Exception as e:
        print(f"  Config FAIL: {e}")
    try:
        from runtime.knowledge_loader import KnowledgePackage
        pkg = KnowledgePackage(ROOT / "knowledge/source/black_tower_test")
        print(f"  Knowledge OK（chests={len(pkg.chests or [])}）")
    except Exception as e:
        print(f"  Knowledge FAIL: {type(e).__name__}: {e}")
    try:
        import runtime.api.commands
        print("  Runtime OK")
    except Exception as e:
        print(f"  Runtime FAIL: {e}")
    try:
        from config import settings
        key = settings.qwen_api_key()
        print(f"  Vision {'OK' if key else 'NO_API_KEY（VLM 不可用，模板路径不受影响）'}")
    except Exception as e:
        print(f"  Vision FAIL: {e}")
    return 0


def cleanup_temp():
    """Bug 220：临时文件统一清理（抽帧残留/临时 json/tmp）。"""
    from pathlib import Path
    ROOT = Path(__file__).resolve().parent.parent
    targets = []
    cap = ROOT / "ingest" / "raw" / "frames" / "capture"
    targets.append((cap, "f_*.jpg"))
    targets.append((cap, "*.tmp"))
    removed = 0
    for d, pat in targets:
        if d.exists():
            for f in d.glob(pat):
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
    if removed:
        print(f"[cleanup] 移除 {removed} 个临时文件")
    return removed


def main():
    _check_python_version()
    _check_venv()
    if "--cleanup" in sys.argv:
        cleanup_temp()
        return 0
    if "--selftest" in sys.argv:
        return selftest()
    if "--gate" in sys.argv:
        from tools import run_gate
        return run_gate.run()
    # 默认：GUI
    from gui import run as gui_run
    gui_run.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
