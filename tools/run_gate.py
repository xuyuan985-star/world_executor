"""统一门禁入口（目标 3：CI 门禁）——一条命令跑完所有可自动化检查。

    python tools/run_gate.py            # 全量（smoke 需 mock 即可跑）
    python tools/run_gate.py --skip-smoke   # 跳过 orchestrator 冒烟

流程：
  [1/7] architecture lint（依赖方向 + 环 + 动态导入 + 危险调用）
  [2/7] security scan（quarantine 自检 + 脱敏单测）
  [3/7] unit checks（AST 全源码 + 关键单测断言）
  [4/7] replay test（行为回放回归）
  [5/7] vision gate（双通道评分门 6 cases）
  [6/7] smoke orchestrator（mock driver 10 场景；真机相关标记 SKIP(real device)）
  [7/7] dry_run（知识包逻辑验证）

任一失败 → 非零退出 + GATE FAIL。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run():
    import argparse
    import os
    parser = argparse.ArgumentParser(description="WorldExecutor 门禁")
    parser.add_argument("--skip-smoke", action="store_true", help="跳过 smoke_orchestrator")
    args = parser.parse_args()

    def py(args_str):
        import shlex
        # Bug 64/65：cwd 固定仓库根 + PYTHONPATH 继承注入（虚拟环境/任意启动目录都稳）
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        r = subprocess.run([sys.executable] + shlex.split(args_str),
                           cwd=str(ROOT), capture_output=True, text=True, env=env)
        return r.returncode == 0, (r.stdout + r.stderr)[-400:]

    def architecture():
        return py("tools/architecture_check.py --json")

    def security():
        import security.quarantine as q
        try:
            # 审查 P1：原硬编码本机用户名——换机器即 FAIL。用任意用户路径
            from pathlib import Path as _P
            t = q.sanitize_text(str(_P.home() / "someuser" / "file")) \
                + q.sanitize_text("C:/Users/anyuser/y")
            assert "<USER>" in t, "sanitize 未生效"
            stub = q.install_pylnk3_stub(verbose=False)
            assert sys.modules.get("pylnk3") is stub, "stub 未注入"
            return True, "quarantine stub + sanitize"
        except Exception as e:
            return False, f"{e!r}"

    def units():
        import ast
        bad = []
        for p in ROOT.rglob("*.py"):
            if any(part in ("__pycache__", ".venv", "March7thAssistant",
                            "failure_reports", "docs") for part in p.parts):
                continue
            try:
                # utf-8-sig：容忍历史 PowerShell 写入的 BOM（U+FEFF）
                ast.parse(p.read_text(encoding="utf-8-sig", errors="ignore"))
            except SyntaxError as e:
                bad.append(f"{p}: {e}")
        if bad:
            return False, f"AST 语法错误: {bad[:3]}"
        from runtime.errors import ErrorCode, code_of
        assert code_of("stale_observation:x") is ErrorCode.OBS_STALE
        assert code_of("bogus") is ErrorCode.UNKNOWN
        return True, "AST + ErrorCode"

    def replay():
        return py("tests/replay/test_action_replay.py")

    def gate_tests():
        return py("tests/vision/test_gate.py")

    def guard_tests():
        return py("tools/action_guard_test.py")

    def planner_tests():
        return py("tests/planner/test_planner.py")

    def smoke():
        return py("tools/smoke_orchestrator.py")

    def pipeline():
        # Bug 100：端到端 pipeline（数据→知识包→校验→dry_run 全链路）
        return py("tools/full_pipeline_test.py")

    def dryrun():
        return py('runtime/dry_run.py "knowledge/source/black_tower_test"')

    ok_all = True
    results = []
    for order, (name, func, skip) in enumerate([
            ("architecture", architecture, False),
            ("security", security, False),
            ("unit checks", units, False),
            ("replay test", replay, False),
            ("vision gate", gate_tests, False),
            ("action guard", guard_tests, False),
            ("planner", planner_tests, False),
            ("smoke", smoke, args.skip_smoke),
            ("pipeline", pipeline, False),
            ("dry_run", dryrun, False)], start=1):
        if skip:
            print(f"[{order}/10] {name} ... SKIP")
            results.append({"name": name, "status": "SKIP"})
            continue
        print(f"[{order}/10] {name} ...")
        ok, detail = func()
        results.append({"name": name, "status": "PASS" if ok else "FAIL",
                        "detail": detail})
        if ok:
            print(f"  PASS {detail or ''}")
        else:
            print(f"  FAIL {detail or ''}")
        ok_all = ok_all and ok
    print("GATE " + ("PASS" if ok_all else "FAIL"))
    # Bug 243：机器可读报告（CI/外部消费）
    try:
        import json as _json
        from pathlib import Path as _P
        from runtime.timeutil import iso_utc
        rep = {"ok": ok_all, "checks": results, "generated_at": iso_utc()}
        out = _P(__file__).resolve().parent.parent / "reports" / "gate.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(rep, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    except Exception:
        pass
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(run())





