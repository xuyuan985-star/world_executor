import os
import sys
import threading
from pathlib import Path

# P0-004：配置读写并发安全（GUI reload 与 runtime get 可能并发）
_config_lock = threading.RLock()

# Bug 206：PyInstaller 打包环境兼容（sys._MEIPASS 指向解包临时目录）
_MEIPASS = getattr(sys, "_MEIPASS", None)
if _MEIPASS:
    ROOT = Path(_MEIPASS)
else:
    ROOT = Path(__file__).resolve().parent.parent


def resource_path(rel):
    """Bug 206：资源文件统一入口（打包/源码环境都正确）。"""
    return ROOT / rel


def data_root():
    """P0-003：用户数据目录（logs/db/快照）——打包环境不写入临时目录。

    优先级：WORLD_EXECUTOR_DATA env > ~/.world_executor > 仓库 logs。
    """
    override = os.environ.get("WORLD_EXECUTOR_DATA")
    if override:
        return Path(override)
    if _MEIPASS:  # 打包环境：用户目录（_MEIPASS 是临时解包目录，会消失）
        return Path.home() / ".world_executor"
    return ROOT / "logs"


def _load_env():
    env = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


_ENV = _load_env()
# 运行时覆盖（GUI 设置页写入，优先于 .env/环境变量——进程内生效）
_runtime_override = {}


def set_override(key, value):
    """GUI 设置页：运行时覆盖配置（不写 .env，当前进程立即生效）。"""
    with _config_lock:
        if value is None:
            _runtime_override.pop(key, None)
        else:
            _runtime_override[key] = str(value)


def get_override(key):
    with _config_lock:
        return _runtime_override.get(key)


def reload_config():
    """Bug 97：运行中重新加载配置（.env/环境变量刷新，无需重启）。

    P0-004：锁保护——reload 与 get 并发不读中间状态。
    """
    global _ENV
    with _config_lock:
        _ENV = _load_env()
    return _ENV


# ---- Bug 112：日志脱敏（traceback/日志可能携带 key/cookie 等敏感值） ----

_SECRET_PATTERNS = [
    (r"(sk-[A-Za-z0-9]{8,})", "sk-***"),
    (r"(Bearer\s+)[A-Za-z0-9._-]{8,}", r"\1***"),
    (r"(SESSDATA=[A-Za-z0-9%._-]{6,})", "SESSDATA=***"),
    (r"(QWEN_API_KEY[=:]\s*)[^\s,;]+", r"\1***"),
    (r"(BILIBILI_COOKIE[=:]\s*)[^\s,;]+", r"\1***"),
]


def redact_secrets(text):
    """脱敏任意文本（日志/异常信息输出前调用）。"""
    if not text:
        return text
    import re
    for pat, repl in _SECRET_PATTERNS:
        text = re.sub(pat, repl, text)
    return text


def install_log_redaction():
    """给 root logger 挂脱敏 Filter（全局生效，无需逐处调用）。

    P1-005：同时挂到已有 handler 上——handler 级过滤覆盖 exc_info
    格式化输出（traceback 里的 key 也会被清洗）。
    """
    import logging

    class _RedactFilter(logging.Filter):
        def filter(self, record):
            try:
                msg = str(record.msg)
                # 审查 P1：any() 对非空列表恒真——直接按 msg 非空处理
                if msg:
                    record.msg = redact_secrets(msg)
                if record.args:
                    record.args = tuple(
                        redact_secrets(str(a)) if isinstance(a, str) else a
                        for a in record.args)
                if record.exc_info and record.exc_info[1]:
                    try:
                        import traceback
                        tb_text = "".join(
                            traceback.format_exception(*record.exc_info))
                        cleaned = redact_secrets(tb_text)
                        if cleaned != tb_text:
                            record.exc_text = cleaned
                    except Exception:
                        pass
            except Exception:
                pass
            return True

    root = logging.getLogger()
    root.addFilter(_RedactFilter())
    # P1-005：handler 级也挂（traceback 走 exc_text 路径时兜底）
    for h in list(root.handlers):
        h.addFilter(_RedactFilter())


def get(key, default=None):
    # BUG-015：优先级固定为 系统环境变量 > .env > 默认值（部署可覆盖本地配置，
    # 属有意设计）。reload_config 只刷新 .env 层——系统环境不变是预期行为。
    # 运行时覆盖（GUI 设置页）优先于一切
    with _config_lock:
        if key in _runtime_override:
            return _runtime_override[key]
        return os.environ.get(key) or _ENV.get(key) or default


def qwen_api_key():
    return get("QWEN_API_KEY")


def qwen_base_url():
    return get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")


def qwen_model():
    return get("QWEN_MODEL", "qwen-max")


def qwen_vlm_analyze_model():
    return get("QWEN_VLM_ANALYZE_MODEL", "qwen3-vl-plus")


def qwen_vlm_structure_model():
    return get("QWEN_VLM_STRUCTURE_MODEL", "qwen-max")


def qwen_vlm_fallback():
    return [m.strip() for m in get("QWEN_VLM_FALLBACK", "").split(",") if m.strip()]


def qwen_text_fallback():
    return [m.strip() for m in get("QWEN_TEXT_FALLBACK", "").split(",") if m.strip()]


def default_map():
    """GUI 默认加载的大地图（可通过 env/GUI 设置覆盖）。"""
    return get("DEFAULT_MAP", "02_herta_space_station")


def qwen_probe_models():
    """模型探测候选列表（json 数组字符串，默认空 → 调用方用内置默认）。"""
    raw = get("QWEN_PROBE_MODELS", "")
    if not raw:
        return []
    import json
    try:
        val = json.loads(raw)
        return [str(m) for m in val] if isinstance(val, list) else []
    except Exception:
        return []


def validate_config():
    """Bug 76：启动阶段配置校验（缺字段/非法值提前暴露，而非运行中才崩）。

    返回 (ok, [问题列表])。
    Bug 299：关键参数范围限制（min/max 越界即报）。
    """
    problems = []
    base = get("QWEN_BASE_URL", "")
    if base and not base.startswith(("http://", "https://")):
        problems.append("QWEN_BASE_URL 应为 http(s) 地址")
    model = get("QWEN_MODEL", "")
    if model and not model.strip():
        problems.append("QWEN_MODEL 为空")
    vlm = get("QWEN_VLM_ANALYZE_MODEL", "")
    if vlm and not vlm.strip():
        problems.append("QWEN_VLM_ANALYZE_MODEL 为空")
    interval = get("MIN_ACTION_INTERVAL", "")
    if interval:
        try:
            if float(interval) < 0:
                problems.append("MIN_ACTION_INTERVAL 不能为负")
        except ValueError:
            problems.append(f"MIN_ACTION_INTERVAL 非法数值: {interval}")
    # Bug 299：关键数值参数范围
    threshold = get("TEMPLATE_THRESHOLD", "")
    if threshold:
        try:
            v = float(threshold)
            if not (0.0 < v <= 1.0):
                problems.append(f"TEMPLATE_THRESHOLD={v} 应在 (0, 1]（0-1 置信度）")
        except ValueError:
            problems.append(f"TEMPLATE_THRESHOLD 非法数值: {threshold}")
    rate = get("VLM_RATE_PER_MIN", "")
    if rate:
        try:
            if float(rate) < 0:
                problems.append("VLM_RATE_PER_MIN 不能为负")
        except ValueError:
            problems.append(f"VLM_RATE_PER_MIN 非法数值: {rate}")
    return (not problems), problems


def knowledge_root():
    return ROOT / "knowledge"


def runtime_db_path():
    return ROOT / "runtime.db"


def march7_root():
    return ROOT / "March7thAssistant"
