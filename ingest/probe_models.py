import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from config import settings

CANDIDATES = [
    "qwen3-vl-flash",
    "qwen3-vl-plus",
    "qwen-vl-plus",
    "qwen-vl-max",
    "qwen3.5-flash",
    "qwen3.5-plus",
    "qwen3-flash",
    "qwen3-plus",
    "qwen3-omni-flash",
    "qwen-omni-turbo",
]

BASE = settings.qwen_base_url()
# Bug 57：API Key 未配置不发请求（Bearer None 是无意义请求）
_API_KEY = settings.qwen_api_key()
HEADERS = {"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"} if _API_KEY else {}


def probe(model):
    # Bug 57：key 缺失 → 明确返回（不再裸发无凭据请求）
    if not _API_KEY:
        return "NO_API_KEY"
    url = f"{BASE.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    try:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
        if resp.status_code == 200:
            return "OK"
        body = ""
        try:
            body = resp.json().get("error", {}).get("message", resp.text[:120])
        except Exception:
            body = resp.text[:120]
        return f"FAIL {resp.status_code}: {body}"
    except Exception as e:
        return f"ERR: {e}"


def main():
    # Bug 58：输出目录基于仓库根绝对定位
    out = Path(__file__).resolve().parent.parent / "ingest" / "raw" / "probe_results.json"
    results = {}
    for m in CANDIDATES:
        r = probe(m)
        results[m] = r
        print(f"{m:<28} {r}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
