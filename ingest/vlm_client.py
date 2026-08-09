import base64
import json
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
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


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

    def _chat(self, messages, model=None, fallback=None, temperature=0.2, max_tokens=4096):
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
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                if resp.status_code in self.QUOTA_ERRORS:
                    body = ""
                    try:
                        body = resp.json().get("error", {}).get("message", "")
                    except Exception:
                        pass
                    if "quota" in body.lower() or "free" in body.lower():
                        raise QuotaExhausted(f"{model}: {body[:100]}")
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except QuotaExhausted:
                raise
            except Exception:
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
