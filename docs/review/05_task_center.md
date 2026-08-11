# R5 任务中心审查（2026-08-12）

## 架构（0.6.0 回滚后终态）

**QProcess 子进程模式**——m7 任务在独立进程跑，GUI 与 m7 零状态共享：

```
TaskCenterPage._start_task
 └─ TaskProcess(task_id)  [QProcess 封装]
     ├─ 管理员检查（fail-closed：m7 main.py 顶层 pyuac 提权会脱离 QProcess）
     ├─ M7_ROOT/M7_PYTHON 路径推导（frozen=exe 目录 / 源码=项目内 m7/ + m7_venv）
     ├─ env：MARCH7TH_DOCKER_STARTED=true（跳 first_run + 结束 pause）
     │        PYTHONUTF8=1 + PYTHONIOENCODING=utf-8（防 GBK 乱码）
     ├─ python -u m7_launcher.py <task>（-u 防 stdout 缓冲）
     ├─ readyReadStandardOutput/Error → UTF-8 解码 → log_line（GUI 线程投递，可靠）
     └─ stop = kill()（m7 任务幂等，中断安全）+ _stopped_by_user 标记
```

## m7_launcher.py（子进程入口）

1. sys.path 注入 WORLD_ROOT（cwd=M7 时找不到 security 包）
2. `require_m7_path(M7)`：目录结构校验（module/ 必须有；无 config.yaml 时 assets/ 必须有）
3. `install_pylnk3_stub()`：防投毒包
4. 路径推导：项目内 `m7/` 主路径 → 外部 `March7thAssistant` 兜底
5. os.chdir(M7) + sys.path.insert(0, M7)
6. `sys.argv = [main.py] + argv[1:]` 伪造 m7 argparse 输入
7. `runpy.run_module("main", run_name="__main__")`

## pylnk3 投毒包隔离（security/quarantine.py）

- PyPI pylnk3 是被投毒包——真实实现禁用，stub 注入
- `Lnk` stub：path/arguments/work_dir/icon 等占位属性；其余 `__getattr__` raise
- **审计结论（代码内注明）**：module/config/__init__.py 同行的 base64 exec payload 仍会执行——已解码审计 = 防破解/免责声明校验（%ProgramData% disclaimer + sponsor.jpg MD5），无网络/无数据窃取；不匹配 sys.exit(0)
- sanitize_text：`C:\Users\<用户名>` → `C:\Users\<USER>`（str.replace 非 re.sub——反斜杠序列坑）

## 更新链（m7_updater.py + update_runner.py）

- UpdateProcess（QProcess，MergedChannels）→ m7_updater.py
- 更新源：外部 March7thAssistant（有 .git）或项目内 m7/.git → git fetch + pull --ff-only → robocopy /MIR 同步到运行时副本（排除 .git/logs/__pycache__/.github/tests/config.yaml）
- 依赖同步：m7 requirements 过滤 pylnk3 → pip install 到 m7_venv
- 完整性提示：sponsor.jpg md5（launcher 防篡改 payload 依赖）

## 任务配置（gui/tasks/config.py）

- ruamel.yaml 读写 m7/config.yaml（保注释）；写前 .bak 备份；空文本不写（防关键路径被清空）
- SCHEMA 322 键按组管理（通用/日常/体力/挑战/周常/工具）——只做关键标量，列表复杂配置提示改 yaml
- config_dialog：TaskConfigDialog 按 schema 动态生成表单

## 可疑点（阶段二验证）

1. **update_runner.py 兜底路径 `.venv` 已删除**（CLAUDE.md：.venv 3.11 已删）——`py.exists()` 判定会 false，无害但死代码
2. **m7_updater `git pull --ff-only` 失败后无回滚**——同步中断可能留下不一致副本（robocopy /MIR 原子性无保障）；失败时 log 提示可继续用 git 源，可接受
3. TaskProcess.start 中 `self._proc = proc` 在 `proc.start()` 之后——若 start 同步失败（FailedToStart 异步信号），_proc 非 None 但 running False——`stop()` 判 `self._proc is not None and self.running` → False，不会误杀。OK
4. TaskProcess 无 waitForFinished 超时（shutdown 有 3s）——stop 后 immediately _proc 置 None？TaskCenterPage._on_finished 才清 _proc；shutdown 有 waitForFinished(3000)。OK
5. 任务失败退出码只展示不重试——设计如此（m7 任务幂等，用户手动重试）
