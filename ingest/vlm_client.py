import base64
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import settings


@dataclass
class SegmentNarrative:
    segment: int
    timestamp: str
    description: str
    shots: list = field(default_factory=list)


class QuotaExhausted(Exception):
    pass


class VLMProvider:
    def analyze_frames(self, frames, captions, context) -> Optional[SegmentNarrative]:
        raise NotImplementedError

    def structure_text(self, narratives) -> str:
        raise NotImplementedError


def _encode_image(path: str) -> str:
    # Bug 162：上传前压缩（长边 1280 + JPEG 质量 80）——高分辨率帧 10MB+ 会失败
    from PIL import Image
    img = Image.open(path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    max_side = 1280
    w, h = img.size
    if max(w, h) > max_side:
        ratio = max_side / max(w, h)
        img = img.resize((round(w * ratio), round(h * ratio)),
                         Image.LANCZOS)
    import io
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


class RateLimiter:
    """Bug 228：全局限流（令牌桶）——多线程请求共享，防 API rate limit。

    rate_per_min=0 表示不限流。
    """

    def __init__(self, rate_per_min=0):
        import threading
        self.rate = rate_per_min
        self._lock = threading.Lock()
        self._tokens = float(rate_per_min)
        self._last = time.time()

    def wait(self):
        if self.rate <= 0:
            return
        with self._lock:
            now = time.time()
            self._tokens = min(float(self.rate),
                               self._tokens + (now - self._last) * self.rate / 60.0)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return
            wait_s = (1 - self._tokens) * 60.0 / self.rate
            self._tokens = 0.0
        time.sleep(wait_s)


def _vlm_rate_per_min():
    """读 VLM_RATE_PER_MIN（config.settings.get 返回原始字符串/None）。
    审查：非法值（非数字）→ 返回 0，绝不抛 ValueError（原 int() 直接转——
    配置写错会让 vlm_client import 失败、管线全挂）。"""
    try:
        return int(settings.get("VLM_RATE_PER_MIN", 0) or 0)
    except (TypeError, ValueError):
        return 0


# 全局共享限流器（模块级单例）——config.settings.get() 读环境/配置
# （原 getattr(settings, "VLM_RATE_PER_MIN", 0) 恒 0——模块无该属性，限流从未生效）
GLOBAL_RATE_LIMITER = RateLimiter(_vlm_rate_per_min())


class QwenVLProvider(VLMProvider):
    QUOTA_ERRORS = (403, 429)

    def __init__(self, api_key=None, base_url=None, model=None, structure_model=None,
                 vlm_fallback=None, text_fallback=None):
        self.api_key = api_key or settings.qwen_api_key()
        self.base_url = base_url or settings.qwen_base_url()
        self.model = model or settings.qwen_vlm_analyze_model()
        self.structure_model = structure_model or settings.qwen_vlm_structure_model()
        self.vlm_fallback = vlm_fallback or settings.qwen_vlm_fallback()
        self.text_fallback = text_fallback or settings.qwen_text_fallback()
        self.timeout = 120
        self.retries = 1

    def chat(self, messages, **kwargs):
        """公开对话接口（Bug 16：外部统一调用，不依赖私有 _chat）。"""
        return self._chat(messages, **kwargs)

    def _chat(self, messages, model=None, fallback=None, temperature=0.2,
              max_tokens=None):
        # Bug 115：默认输出限长 512（防 token 爆炸/超模型上限——omni 上限 2048）
        if max_tokens is None:
            max_tokens = 512
        models = [model or self.model] + list(fallback or [])
        last_err = None
        for m in models:
            try:
                return self._post(m, messages, temperature, max_tokens)
            except QuotaExhausted as e:
                last_err = e
                continue
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"模型 {models} 全部失败: {last_err}")

    def _post(self, model, messages, temperature, max_tokens):
        import time as _t
        from runtime.circuit_breaker import VLM_BREAKER
        from runtime.metrics import METRICS
        # Bug 507：熔断——连续失败不持续打 API（冷却后探针恢复）
        if not VLM_BREAKER.allow():
            METRICS.model_call(0, error="circuit_open")
            raise QuotaExhausted(f"{model}: 熔断中（连续失败，冷却后自动恢复）")
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        for attempt in range(self.retries + 1):
            try:
                GLOBAL_RATE_LIMITER.wait()  # Bug 228：全局限流（多线程共享）
                t0 = _t.time()
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                elapsed_ms = (_t.time() - t0) * 1000
                if resp.status_code in self.QUOTA_ERRORS:
                    body = ""
                    try:
                        body = resp.json().get("error", {}).get("message", "")
                    except Exception:
                        pass
                    if "quota" in body.lower() or "free" in body.lower():
                        METRICS.model_call(elapsed_ms, error=f"quota:{body[:60]}")
                        raise QuotaExhausted(f"{model}: {body[:100]}")
                resp.raise_for_status()
                data = resp.json()
                usage = (data.get("usage") or {})
                METRICS.model_call(
                    elapsed_ms,
                    prompt_tokens=usage.get("prompt_tokens") or 0,
                    completion_tokens=usage.get("completion_tokens") or 0)
                VLM_BREAKER.record_success()  # 成功 → 计数清零
                return data["choices"][0]["message"]["content"]
            except QuotaExhausted:
                raise
            except Exception as e:
                # Bug 294：错误分类统计（timeout/rate_limit/auth/json）
                METRICS.model_call(0, error=f"{type(e).__name__}: {e}")
                VLM_BREAKER.record_failure()  # Bug 507：失败计数
                if attempt >= self.retries:
                    raise
                time.sleep(2 * (attempt + 1))

    def analyze_frames(self, frames, captions, context) -> Optional[SegmentNarrative]:
        content = []
        for f in frames:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_encode_image(f)}"}})
        if captions:
            content.append({"type": "text", "text": f"字幕:\n{captions}"})
        content.append({"type": "text", "text": context})

        messages = [
            {"role": "system", "content": (
                "你是崩坏星穹铁道攻略视频的考古员。逐帧观察画面与字幕，只输出该视频段的事件描述（角色做了什么、经过什么、宝箱在哪里）。"
                "禁止输出操作步骤、按键、时长、坐标。"
            )},
            {"role": "user", "content": content},
        ]
        text = self._chat(messages, fallback=self.vlm_fallback)
        return SegmentNarrative(segment=0, timestamp="", description=text)

    def structure_text(self, narratives) -> str:
        text = "\n".join(n.description for n in narratives)
        messages = [
            {"role": "system", "content": "将事件描述整理为结构化 JSON 事件清单，字段：time, event, object, detail。不要添加虚构内容。"},
            {"role": "user", "content": text},
        ]
        return self._chat(messages, model=self.structure_model, fallback=self.text_fallback)


def get_provider(name="qwen") -> VLMProvider:
    if name == "qwen":
        return QwenVLProvider()
    raise ValueError(f"未知 VLM provider: {name}")


def list_available_models(api_key=None, base_url=None):
    url = f"{(base_url or settings.qwen_base_url()).rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key or settings.qwen_api_key()}"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", [])]
