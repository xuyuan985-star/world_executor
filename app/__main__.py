"""P0-002：启动入口拆分——__main__ 只做参数路由。

职责分离：cli（参数）→ launcher（环境/生命周期）→ 具体命令。
"""
import os
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
    # 提权链路探针
    try:
        import ctypes as _c
        with open(ROOT / "logs" / "elevate_trace.log", "a", encoding="utf-8") as f:
            import time as _t
            f.write(f"{_t.strftime('%H:%M:%S')} ENTRY pid={os.getpid()} "
                    f"admin={bool(_c.windll.shell32.IsUserAnAdmin())} "
                    f"argv={sys.argv}\n")
    except Exception:
        pass
    try:
        from app.launcher import run
        sys.exit(run(sys.argv[1:]))
    except BaseException:
        # pythonw 下启动异常静默死——落盘可查
        import traceback
        from pathlib import Path
        try:
            err = ROOT / "logs" / "startup_error.log"
            err.parent.mkdir(parents=True, exist_ok=True)
            with open(err, "a", encoding="utf-8") as f:
                f.write("\n===== app entry =====\n")
                f.write(traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
