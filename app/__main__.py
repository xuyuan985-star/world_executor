"""P0-002：启动入口拆分——__main__ 只做参数路由。

职责分离：cli（参数）→ launcher（环境/生命周期）→ 具体命令。
"""
import sys


def main():
    from app.launcher import run
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
