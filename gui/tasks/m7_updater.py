"""m7 模块更新脚本（QProcess 子进程执行——git pull + 依赖同步）。

架构（0.6.0 回滚后）：
- 运行时副本 = 项目内 m7/（无 .git——拷贝内化，随项目分发）
- git 更新源 = 外部镜像 March7thAssistant（有 .git 时）或项目内 m7/.git
  （未来保留 git 时）——git fetch/pull（ff-only 防冲突）后同步覆盖副本
- m7_venv 依赖同步（requirements 排除投毒包 pylnk3——quarantine stub 已挡）
- config.yaml 未被 git 跟踪（本地配置不动）。输出每行一个进度，GUI 日志区
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
# 运行时副本：项目内 m7/（主路径，自包含）
M7 = WORLD_ROOT / "m7"
# 外部镜像（更新源——有 .git 时优先；项目内副本无 .git 无法 git pull）
M7_UPSTREAM = WORLD_ROOT.parent / "March7thAssistant"
if not (M7_UPSTREAM / ".git").exists() and (M7 / ".git").exists():
    M7_UPSTREAM = M7
VENV_PY = WORLD_ROOT / "m7_venv" / "Scripts" / "python.exe"
REQ_FILTERED = WORLD_ROOT / "logs" / "m7_req_filtered.txt"


def log(msg):
    print(msg, flush=True)


def run(cmd, cwd, timeout=600):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r


def git(args, cwd=None):
    r = run(["git"] + args, cwd or M7_UPSTREAM)
    return r.stdout.strip() if r.returncode == 0 else ""


def _head(cwd=None):
    return git(["rev-parse", "HEAD"], cwd)


def _sync_to_runtime():
    """git 源更新后同步到运行时副本（项目内 m7/）。

    排除：.git（不复制历史）、logs/__pycache__（运行残留）、config.yaml
    （本地配置不动——覆盖会丢用户设置）。
    """
    if M7_UPSTREAM == M7:
        return True
    if not M7_UPSTREAM.exists():
        log(f"[更新] 外部镜像不存在: {M7_UPSTREAM}")
        return False
    # robocopy：/MIR 镜像（多删少补）+ /XD 排除目录 + /XF 排除文件
    excludes_dir = [".git", "logs", "__pycache__", ".github", "tests"]
    excludes_file = ["config.yaml"]
    cmd = ["robocopy", str(M7_UPSTREAM), str(M7), "/MIR",
           "/XD"] + excludes_dir + ["/XF"] + excludes_file + ["/NFL", "/NDL", "/NJH"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    # robocopy 退出码：0-7 成功（8+ 失败）
    return r.returncode < 8


def check_remote():
    if not (M7_UPSTREAM / ".git").exists():
        log(f"[更新] 未找到 git 镜像（{M7_UPSTREAM}）——"
            "请先准备外部 March7thAssistant 仓库")
        return False
    log(f"[更新] 当前版本: {_head()[:12]}")
    r = run(["git", "fetch", "origin"], M7_UPSTREAM)
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


def do_update():
    before = _head()
    r = run(["git", "pull", "--ff-only"], M7_UPSTREAM)
    if r.returncode != 0:
        log(f"[更新] git pull 失败: {r.stderr.strip()[:300]}")
        return False
    after = _head()
    log(f"[更新] pull 完成: {before[:12]} → {after[:12]}")
    if before != after or not (M7 / "main.py").exists():
        # 同步到项目内运行时副本
        if not _sync_to_runtime():
            log("[更新] 同步到运行时副本失败（可继续用 git 源运行）")
            return False
        log(f"[更新] 已同步到运行时副本: {M7}")
    else:
        log("[更新] 版本未变化，副本已是最新")
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
    if not (M7 / "main.py").exists():
        log(f"[更新] 运行时副本缺失 main.py: {M7}——请运行 tools/setup_m7.py")
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
