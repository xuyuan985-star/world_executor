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
HEADERS = {"Authorization": f"Bearer {settings.qwen_api_key()}", "Content-Type": "application/json"}


def probe(model):
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
    results = {}
    for m in CANDIDATES:
        r = probe(m)
        results[m] = r
        print(f"{m:<28} {r}")
    (Path("ingest/raw") / "probe_results.json").parent.mkdir(parents=True, exist_ok=True)
    (Path("ingest/raw") / "probe_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
