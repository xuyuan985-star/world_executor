"""m7 模块更新脚本（QProcess 子进程执行——git pull + 依赖同步）。

m7 是独立维护的仓库（moesnow/March7thAssistant）——我们迁移后在本程序
内更新它：git fetch/pull（ff-only 防冲突）→ m7_venv 依赖同步（requirements
排除投毒包 pylnk3——quarantine stub 已挡）→ 完整性提示（sponsor.jpg 校验
由 launcher 的 payload 决定——更新后如任务异常请检查资产）。

config.yaml 未被 git 跟踪（本地配置不动）。输出每行一个进度，GUI 日志区
实时显示。
"""
import subprocess
import sys
from pathlib import Path

# 强制 UTF-8 输出（QProcess 按 UTF-8 解码——GBK 字节会乱码）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 路径相对推导（禁止硬编码——同事/新环境路径不同）
WORLD_ROOT = Path(__file__).resolve().parent.parent.parent
M7 = WORLD_ROOT.parent / "March7thAssistant"
VENV_PY = WORLD_ROOT / "m7_venv" / "Scripts" / "python.exe"
REQ_FILTERED = WORLD_ROOT / "logs" / "m7_req_filtered.txt"


def log(msg):
    print(msg, flush=True)


def run(cmd, cwd, timeout=600):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r


def check_remote():
    log(f"[更新] 当前版本: {_head()[:12]}")
    r = run(["git", "fetch", "origin"], M7)
    if r.returncode != 0:
        log(f"[更新] git fetch 失败: {r.stderr.strip()[:200]}")
        return False
    ahead = _head()
    behind = git(["rev-parse", "origin/main"]).strip()
    if ahead == behind:
        log(f"[更新] 已是最新版本（{ahead[:12]}）")
        return True
    log(f"[更新] 发现新版本: {ahead[:12]} → {behind[:12]}")
    return True


def git(args):
    r = run(["git"] + args, M7)
    return r.stdout.strip() if r.returncode == 0 else ""


def _head():
    return git(["rev-parse", "HEAD"])


def do_update():
    before = _head()
    r = run(["git", "pull", "--ff-only"], M7)
    if r.returncode != 0:
        log(f"[更新] git pull 失败: {r.stderr.strip()[:300]}")
        return False
    after = _head()
    log(f"[更新] pull 完成: {before[:12]} → {after[:12]}")
    if before == after:
        return True
    # 依赖同步（requirements 排除 pylnk3——投毒包由 quarantine stub 挡）
    req = M7 / "requirements.txt"
    if req.exists():
        lines = [l.split(";")[0].strip() for l in req.read_text(encoding="utf-8")
                 .splitlines() if l.strip() and not l.strip().startswith("#")
                 and "pylnk3" not in l]
        REQ_FILTERED.parent.mkdir(parents=True, exist_ok=True)
        REQ_FILTERED.write_text("\n".join(lines), encoding="utf-8")
        log("[更新] 同步 m7_venv 依赖（排除 pylnk3）…")
        r = run([str(VENV_PY), "-m", "pip", "install", "-q", "-r", str(REQ_FILTERED)],
                M7, timeout=1800)
        if r.returncode != 0:
            log(f"[更新] 依赖同步失败: {r.stderr.strip()[:300]}")
            return False
        log("[更新] 依赖同步完成")
    # 完整性提示（sponsor.jpg——launcher 的防篡改 payload 依赖它）
    import hashlib
    sp = M7 / "assets" / "app" / "images" / "sponsor.jpg"
    if sp.exists():
        h = hashlib.md5(sp.read_bytes()).hexdigest()
        log(f"[更新] sponsor.jpg md5={h[:16]}…（如任务异常请检查资产完整性）")
    log("[更新] m7 更新完成——新版本资产已生效")
    return True


def main():
    if not M7.exists():
        log(f"[更新] March7thAssistant 不存在: {M7}")
        sys.exit(1)
    try:
        if not check_remote():
            sys.exit(1)
        if not do_update():
            sys.exit(1)
    except Exception as e:
        log(f"[更新] 更新异常: {type(e).__name__}: {e}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
