"""P0-002：启动入口拆分——__main__ 只做参数路由。

职责分离：cli（参数）→ launcher（环境/生命周期）→ 具体命令。
"""
import sys


def main():
    # pythonw 启动（无控制台）时 stdout/stderr 为 None——print 会崩，重定向
    if sys.stdout is None:
        import io
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        import io
        sys.stderr = io.StringIO()
    from app.launcher import run
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
