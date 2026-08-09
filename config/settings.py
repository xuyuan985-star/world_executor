import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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


def reload_config():
    """Bug 97：运行中重新加载配置（.env/环境变量刷新，无需重启）。"""
    global _ENV
    _ENV = _load_env()
    return _ENV


def get(key, default=None):
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
    return (not problems), problems


def knowledge_root():
    return ROOT / "knowledge"


def runtime_db_path():
    return ROOT / "runtime.db"


def march7_root():
    return ROOT / "March7thAssistant"
