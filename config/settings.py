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


def get(key, default=None):
    return os.environ.get(key) or _ENV.get(key) or default


def qwen_api_key():
    return get("QWEN_API_KEY")


def qwen_base_url():
    return get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")


def qwen_model():
    return get("QWEN_MODEL", "qwen-plus")


def qwen_vlm_analyze_model():
    return get("QWEN_VLM_ANALYZE_MODEL", "qwen3-vl-flash")


def qwen_vlm_structure_model():
    return get("QWEN_VLM_STRUCTURE_MODEL", "qwen-plus")


def qwen_vlm_fallback():
    return [m.strip() for m in get("QWEN_VLM_FALLBACK", "").split(",") if m.strip()]


def qwen_text_fallback():
    return [m.strip() for m in get("QWEN_TEXT_FALLBACK", "").split(",") if m.strip()]


def knowledge_root():
    return ROOT / "knowledge"


def runtime_db_path():
    return ROOT / "runtime.db"


def march7_root():
    return ROOT / "March7thAssistant"
