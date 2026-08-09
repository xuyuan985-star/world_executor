import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import json
import re
import subprocess

from ingest.vlm_client import QwenVLProvider

FRAME_DIR = ROOT / "ingest/raw/frames/capture"
RESULTS_FILE = ROOT / "ingest/raw/frames/capture/results.json"
FPS_INTERVAL = 3
SCALE = 1280


def check_disk_space(min_free_mb=2000, target=None):
    """Bug 221：抽帧/下载前磁盘空间检查（不足提前拒绝）。"""
    import shutil
    target = target or FRAME_DIR
    try:
        usage = shutil.disk_usage(target)
        free_mb = usage.free / (1024 * 1024)
        if free_mb < min_free_mb:
            raise RuntimeError(
                f"磁盘空间不足（剩余 {free_mb:.0f}MB < 需要 {min_free_mb}MB）")
        return free_mb
    except OSError:
        return None


def video_fps(video):
    """Bug 226：ffprobe 读视频帧率（抽帧间隔按 FPS 调整）。"""
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate", "-of",
             "csv=p=0", str(video)], capture_output=True, text=True, timeout=30)
        num, _, den = r.stdout.strip().partition("/")
        num, den = int(num or 0), int(den or 0)
        return num / den if den else None
    except Exception:
        return None


def extract_frames(video, scale=SCALE, interval=None, max_frames=300):
    """Bug 172：2s 密集固定采样（默认）不漏短现目标；Bug 171：帧数上限。

    间隔与上限互斥保障：短间隔 = 不漏关键帧；上限 = 长视频不爆 VLM 请求。
    Bug 226：高帧率视频（120fps）按比例加密采样。
    """
    # Bug 221：抽帧前磁盘检查（防写一半爆盘）
    check_disk_space()
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    # Bug 47：抽帧前清空旧帧（防第二次处理混入上次视频残留）
    for f in FRAME_DIR.glob("f_*.jpg"):
        f.unlink()
    iv = min(interval or FPS_INTERVAL, 2)  # Bug 172：默认 2s 采样（不漏 1-2s 短现目标）
    fps = video_fps(video)
    if fps and fps > 60:  # Bug 226：120fps 视频时间密度同 30fps 的一半
        iv = max(1, iv // 2)
    vf = f"fps=1/{iv},scale={scale}:-1"
    try:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
            "-vf", vf,
            str(FRAME_DIR / "f_%04d.jpg"),
        ], check=True)
    except subprocess.CalledProcessError as e:
        # Bug 48：抽帧失败带视频上下文（用户知道哪个视频/什么命令失败）
        raise RuntimeError(f"视频抽帧失败: {video}（ffmpeg 返回 {e.returncode}）") from e
    frames = sorted(FRAME_DIR.glob("f_*.jpg"))
    # Bug 171：单视频帧数上限（超长视频均匀采样，防 VLM 请求爆炸）
    if len(frames) > max_frames:
        step = len(frames) / max_frames
        keep = {frames[int(i * step)] for i in range(max_frames)}
        for f in frames:
            if f not in keep:
                f.unlink()
        frames = sorted(FRAME_DIR.glob("f_*.jpg"))
    return frames


PROMPT_VERSION = "v3"  # Bug 449：prompt 版本——改动需 bump（结果可复现/对比）


PROMPT = (
    f"[prompt v{PROMPT_VERSION}] "
    "这是一段崩坏星穹铁道攻略视频的单帧。逐项回答，没有就写none：\n"
    "1. 画面中央区域是否有可互动的普通宝箱（金色/蓝绿色箱体）？若有给出bbox [x1,y1,x2,y2]（0-1000像素坐标系）。\n"
    "2. 画面是否有门（通往其他房间的入口/门框/自动门）？若有给出bbox。\n"
    "3. 画面是否出现明显的地标（雕像/大型设备/独特场景）？若有给出bbox和简短名字。\n"
    "4. 画面显示的是哪个房间（从地图或环境判断）？\n"
    "输出JSON，不要多余内容。\n"
    "输出schema（必须包含）：{\"observation_only\": true, \"chest\": {\"found\": false, \"bbox\": null}, "
    "\"door\": {\"found\": false, \"bbox\": null}, \"landmark\": {\"found\": false, \"bbox\": null, \"name\": null}, "
    "\"room\": null}\n"
    "注意：observation_only 恒为 true——这是知识采集输出，仅供观察与知识入库，"
    "绝不包含任何 click/action/坐标点击意图字段。"
)


# Bug 158：VLM 响应缓存（同帧 hash → 同结果，重跑不重复扣费）
# Bug 218：TTL + 容量——帧内容缓存 24h 后失效，256 条上限
_VLM_CACHE = {}
_VLM_CACHE_MAX = 256
_VLM_CACHE_TTL = 24 * 3600


def _frame_hash(frame_path):
    import hashlib
    h = hashlib.md5()
    with open(frame_path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def ask_frame(provider, frame, index, use_cache=True):
    import time as _time
    try:
        key = None
        if use_cache and provider is not None and frame is not None:
            key = _frame_hash(frame)
            hit = _VLM_CACHE.get(key)
            if hit and _time.time() - hit[1] < _VLM_CACHE_TTL:
                return hit[0]
        n = provider.analyze_frames([str(frame)], "", PROMPT)
        text = n.description.strip()
        data = None
        # Bug 49：非贪婪正则会截断嵌套 JSON——直接取首尾花括号全段
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except Exception:
                data = None
        if isinstance(data, dict):
            # Bug 161：模型响应字段兼容（bbox/box 双别名）
            for holder in (data.get("chest"), data.get("door"),
                           data.get("landmark")):
                if isinstance(holder, dict) and holder.get("bbox") is None \
                        and holder.get("box") is not None:
                    holder["bbox"] = holder["box"]
            data.setdefault("observation_only", True)
            result = data
        else:
            # Bug 50：JSON 解析失败保存原始响应（VLM 格式问题可追查）
            result = {"error": "json_parse_failed", "raw": text[:2000],
                      "index": index}
        if key is not None:
            _VLM_CACHE[key] = (result, _time.time())
            if len(_VLM_CACHE) > _VLM_CACHE_MAX:
                _VLM_CACHE.clear()
        return result
    except Exception as e:
        return {"error": str(e), "index": index}


def main():
    video = sys.argv[1]
    scale = int(sys.argv[2]) if len(sys.argv) > 2 else SCALE
    frames = extract_frames(video, scale=scale)
    print(f"抽帧 {len(frames)} 张")
    provider = QwenVLProvider()
    results = []
    for i, f in enumerate(frames):
        data = ask_frame(provider, f, i)
        print(f"  f_{i:04d} ({f.stat().st_size//1024}KB) -> {json.dumps(data, ensure_ascii=False)[:160]}")
        results.append({"frame": f.name, "data": data})
        # Bug 51：结果原子写——临时文件完成后 rename（防中断损坏 results.json）
        tmp = RESULTS_FILE.with_name(RESULTS_FILE.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
        tmp.replace(RESULTS_FILE)


if __name__ == "__main__":
    main()
