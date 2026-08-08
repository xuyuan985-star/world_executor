import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import re
import subprocess

from ingest.vlm_client import QwenVLProvider

FRAME_DIR = Path("ingest/raw/frames/capture")
FPS_INTERVAL = 3


def extract_frames(video):
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
        "-vf", f"fps=1/{FPS_INTERVAL},scale=640:-1",
        str(FRAME_DIR / "f_%04d.jpg"),
    ], check=True)
    return sorted(FRAME_DIR.glob("f_*.jpg"))


PROMPT = (
    "这是一段崩坏星穹铁道攻略视频的单帧。逐项回答，没有就写none：\n"
    "1. 画面中央区域是否有可互动的普通宝箱（金色/蓝绿色箱体）？若有给出bbox [x1,y1,x2,y2]（0-1000像素坐标系）。\n"
    "2. 画面是否有门（通往其他房间的入口/门框/自动门）？若有给出bbox。\n"
    "3. 画面是否出现明显的地标（雕像/大型设备/独特场景）？若有给出bbox和简短名字。\n"
    "4. 画面显示的是哪个房间（从地图或环境判断）？\n"
    "输出JSON，不要多余内容。"
)


def ask_frame(provider, frame, index):
    try:
        n = provider.analyze_frames([str(frame)], "", PROMPT)
        text = n.description.strip()
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {}
        return data
    except Exception as e:
        return {"error": str(e), "index": index}


def main():
    video = sys.argv[1]
    frames = extract_frames(video)
    print(f"抽帧 {len(frames)} 张")
    provider = QwenVLProvider()
    results = []
    for i, f in enumerate(frames):
        data = ask_frame(provider, f, i)
        print(f"  f_{i:04d} ({f.stat().st_size//1024}KB) -> {json.dumps(data, ensure_ascii=False)[:160]}")
        results.append({"frame": f.name, "data": data})
        with open("ingest/raw/frames/capture/results.json", "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
