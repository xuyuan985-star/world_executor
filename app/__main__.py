"""P0-002：启动入口拆分——__main__ 只做参数路由。

职责分离：cli（参数）→ launcher（环境/生命周期）→ 具体命令。
审查 P0-4：SystemExit 是正常退出（sys.exit(0)），不能被当崩溃捕获。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    # pythonw 启动（无控制台）时 stdout/stderr 为 None——print 会崩，重定向
    if sys.stdout is None:
        import io
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        import io
        sys.stderr = io.StringIO()
    # 崩溃捕获（0xC0000005 等原生崩溃）：faulthandler 在 SIGSEGV 时 dump
    # 所有线程的 Python 栈到日志——pythonw 无控制台，必须显式落盘。
    try:
        import faulthandler
        import threading as _threading
        _crash_log = ROOT / "logs" / "crash_trace.log"
        _crash_log.parent.mkdir(parents=True, exist_ok=True)
        _f = open(_crash_log, "a", encoding="utf-8", buffering=1)
        import time as _time
        _f.write(f"\n===== process start {_time.strftime('%Y-%m-%d %H:%M:%S')} "
                 f"argv={sys.argv} =====\n")
        faulthandler.enable(file=_f, all_threads=True)

        def _thread_excepthook(args):
            try:
                with open(_crash_log, "a", encoding="utf-8") as _ef:
                    _ef.write(f"\n[thread {args.thread.name}] {args.exc_type.__name__}: "
                              f"{args.exc_value}\n")
                    import traceback as _tb
                    _tb.print_tb(args.exc_traceback, file=_ef)
            except Exception:
                pass

        _threading.excepthook = _thread_excepthook
    except Exception:
        pass
    # 退出路径探针（排查"窗口消失但无崩溃记录"）：atexit 只在正常退出执行，
    # os._exit / 原生崩溃不执行——可区分退出方式。
    try:
        import atexit as _atexit
        import time as _time2

        def _on_exit():
            try:
                with open(ROOT / "logs" / "exit_trace.log", "a",
                          encoding="utf-8") as _ef:
                    _ef.write(f"{_time2.strftime('%Y-%m-%d %H:%M:%S')} "
                              f"atexit fired — normal interpreter exit\n")
            except Exception:
                pass

        _atexit.register(_on_exit)
    except Exception:
        pass
    try:
        from app.launcher import run
        code = run(sys.argv[1:])
        sys.exit(code)
    except SystemExit:
        raise  # 正常退出——不捕获
    except Exception:
        # pythonw 下启动异常静默死——落盘可查
        import traceback
        try:
            err = ROOT / "logs" / "startup_error.log"
            err.parent.mkdir(parents=True, exist_ok=True)
            with open(err, "a", encoding="utf-8") as f:
                f.write("\n===== app entry =====\n")
                f.write(traceback.format_exc())
        except Exception:
            pass
        # 退出保护：异常退出前若有运行中 QThread（任务线程等），Qt 析构必
        # 0xC0000409——os._exit 跳过析构
        try:
            from gui.tasks.runner import active_task_threads
            if active_task_threads():
                import os as _os
                _os._exit(0)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
