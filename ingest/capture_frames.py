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


def extract_frames(video, scale=SCALE, interval=None):
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    # Bug 47：抽帧前清空旧帧（防第二次处理混入上次视频残留）
    for f in FRAME_DIR.glob("f_*.jpg"):
        f.unlink()
    iv = interval or FPS_INTERVAL
    try:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
            "-vf", f"fps=1/{iv},scale={scale}:-1",
            str(FRAME_DIR / "f_%04d.jpg"),
        ], check=True)
    except subprocess.CalledProcessError as e:
        # Bug 48：抽帧失败带视频上下文（用户知道哪个视频/什么命令失败）
        raise RuntimeError(f"视频抽帧失败: {video}（ffmpeg 返回 {e.returncode}）") from e
    return sorted(FRAME_DIR.glob("f_*.jpg"))


PROMPT = (
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


def ask_frame(provider, frame, index):
    try:
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
            data.setdefault("observation_only", True)
            return data
        # Bug 50：JSON 解析失败保存原始响应（VLM 格式问题可追查）
        return {"error": "json_parse_failed", "raw": text[:2000],
                "index": index}
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
