"""m7 环境自动准备（同事/新机器一键就绪）：

1. March7thAssistant 缺失 → git clone 官方仓库（同级目录）
2. m7_venv（Python 3.12+——m7 官方要求）缺失 → 自动查找 py 3.12/3.13/3.14
   创建专用 venv + 装 m7 requirements（排除投毒包 pylnk3——quarantine stub 挡）

用法：python tools/setup_m7.py [--check-only]
  --check-only：只报告状态不执行（诊断用）
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
M7 = ROOT.parent / "March7thAssistant"
M7_VENV = ROOT / "m7_venv"

REQUIREMENTS = M7 / "requirements.txt"
FILTERED_REQ = ROOT / "m7_requirements_nopylnk.txt"


def log(msg):
    print(f"[setup-m7] {msg}", flush=True)


def run(cmd, cwd, timeout=1800):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        log(f"  命令失败: {' '.join(cmd)[:120]}")
        log(f"  {r.stderr.strip()[-300:]}")
    return r


def find_python312_plus():
    """找 Python 3.12+（py launcher 优先，否则 where python 版本检查）。"""
    for ver in ("3.14", "3.13", "3.12"):
        r = run(["py", f"-{ver}", "-c", "import sys; print(sys.version_info[:2])"],
                ROOT, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return f"py -{ver}"
    # py launcher 无 → 检查默认 python
    r = run([sys.executable, "-c",
             "import sys; print(1 if sys.version_info >= (3,12) else 0)"],
            ROOT, timeout=60)
    if r.returncode == 0 and r.stdout.strip() == "1":
        return sys.executable
    return None


def ensure_m7_repo():
    if (M7 / "main.py").exists():
        log(f"March7thAssistant 已存在（{M7}）")
        return True
    if not shutil.which("git"):
        log("[错误] 未找到 git——无法拉取 March7thAssistant（请安装 git 后重试）")
        return False
    log("克隆 March7thAssistant（官方仓库）…")
    r = run(["git", "clone", "--depth", "1",
             "https://github.com/moesnow/March7thAssistant.git", str(M7)],
            ROOT, timeout=1800)
    return r.returncode == 0 and (M7 / "main.py").exists()


def ensure_m7_venv():
    if (M7_VENV / "Scripts" / "python.exe").exists():
        log("m7_venv 已存在")
        return True
    py = find_python312_plus()
    if py is None:
        log("[错误] 未找到 Python 3.12+（m7 官方要求）——请安装 Python 3.12+ 后重试")
        return False
    log(f"创建 m7_venv（{py}）…")
    r = run(py.split() + ["-m", "venv", str(M7_VENV)], ROOT, timeout=300)
    if r.returncode != 0 or not (M7_VENV / "Scripts" / "python.exe").exists():
        return False
    # 依赖（排除 pylnk3 投毒包）
    if REQUIREMENTS.exists():
        lines = [l.split(";")[0].strip() for l in
                 REQUIREMENTS.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.strip().startswith("#")
                 and "pylnk3" not in l]
        FILTERED_REQ.write_text("\n".join(lines), encoding="utf-8")
        log("安装 m7 依赖（约 1-3 分钟，排除 pylnk3）…")
        r = run([str(M7_VENV / "Scripts" / "python.exe"), "-m", "pip",
                 "install", "-q", "-r", str(FILTERED_REQ)], ROOT, timeout=1800)
        if r.returncode != 0:
            log("[错误] m7 依赖安装失败——请检查网络后重试")
            return False
    log("m7_venv 就绪")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    ok1 = (M7 / "main.py").exists()
    ok2 = (M7_VENV / "Scripts" / "python.exe").exists()
    log(f"March7thAssistant: {'就绪' if ok1 else '缺失'}")
    log(f"m7_venv: {'就绪' if ok2 else '缺失'}")
    if args.check_only:
        return 0 if (ok1 and ok2) else 1

    if not ensure_m7_repo():
        sys.exit(1)
    if not ensure_m7_venv():
        sys.exit(1)
    log("m7 环境准备完成——任务中心可用")
    sys.exit(0)


if __name__ == "__main__":
    main()
