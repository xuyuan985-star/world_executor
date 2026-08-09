import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from config import settings

# Bug 61：模型列表来自配置（新增模型不改代码）
_DEFAULT_CANDIDATES = [
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
CANDIDATES = settings.qwen_probe_models() or _DEFAULT_CANDIDATES

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
        # Bug 59：网络异常（DNS/断连/超时）显式捕获——单模型失败不中断批量
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    except requests.RequestException as e:
        return f"NET_ERR: {e}"
    except Exception as e:
        return f"ERR: {e}"
    # Bug 60：HTTP 状态码显式校验（401/500 不静默当成功）
    if resp.status_code != 200:
        body = ""
        try:
            body = resp.json().get("error", {}).get("message", resp.text[:120])
        except Exception:
            body = resp.text[:120]
        return f"FAIL {resp.status_code}: {body}"
    return "OK"


def main():
    # Bug 58：输出目录基于仓库根绝对定位
    out = Path(__file__).resolve().parent.parent / "ingest" / "raw" / "probe_results.json"
    results = {}
    for m in CANDIDATES:
        r = probe(m)
        results[m] = r
        print(f"{m:<28} {r}")
    out.parent.mkdir(parents=True, exist_ok=True)
    # Bug 62：先写 .new.json，成功才原子替换（中途失败不覆盖旧报告）
    new = out.with_name(out.name + ".new.json")
    new.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    new.replace(out)


if __name__ == "__main__":
    main()
