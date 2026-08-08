"""视频 → 攻略点位 → 自动归档（knowledge/guides 体系）。

用法：
    python ingest/archive_video.py <video.mp4> [--max-frames N] [--dry-run]

流程：
    1. 文件名解析 → 地图/区域（反向匹配 guides 的 map.json / areas/*.json 名称）
    2. ffmpeg 抽帧 → Qwen VLM 识别（chest/door/landmark/room）
    3. 生成点位记录（bbox 中心归一化坐标）
    4. 按类型归档到 maps/<map>/points/<type>.json（去重，id 前缀=map+area）

归档正确性测试：P8 支援舱段5.mp4 → 02_herta_space_station/points/chests.json
"""
import argparse
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.capture_frames import ask_frame, extract_frames  # noqa: E402
from ingest.vlm_client import QwenVLProvider  # noqa: E402

GUIDES = ROOT / "knowledge" / "guides" / "maps"

# 视频文件名 → 地图/区域（名称反向匹配 guides；无匹配则报错）
VIDEO_AREA_OVERRIDES = {
    "支援舱段": "supply_zone",
    "基座舱段": "base_zone",
    "收容舱段": "storage_zone",
    "主控舱段": "master_zone",
    "禁闭舱段": "detention_zone",
}

# 视频文件名 → 大地图目录（跨区域视频，如"黑塔币"全空间站收集）
VIDEO_MAP_OVERRIDES = {
    "黑塔": "02_herta_space_station",
    "雅利洛": "03_jarilo_vi",
    "罗浮": "04_xianzhou_luofu",
    "匹诺康尼": "05_penacony",
    "翁法罗斯": "06_amphoreus",
    "二相乐园": "07_dream_paradise",
}


def resolve_map_area(video_name):
    """文件名 → (map_dir, area_id)。

    视频名通常只含区域名（三重权限_P8_支援舱段5）——
    先按 override 表匹配区域，再反向匹配 areas/*.json 得到所属地图目录。
    """
    stem = Path(video_name).stem
    # 1) override 表：区域关键词 → area_id
    area_id = None
    for key, aid in VIDEO_AREA_OVERRIDES.items():
        if key in stem:
            area_id = aid
            break
    # 2) 地图级 override（跨区域视频：黑塔币等）——region 用地图 id
    for key, mdir in VIDEO_MAP_OVERRIDES.items():
        if key in stem:
            mid = mdir.split("_", 1)[1]
            return mdir, mid, None
    # 3) 遍历所有地图的 areas，找名称匹配的区域文件 → 得地图目录
    for md in sorted(GUIDES.iterdir()):
        if not md.is_dir():
            continue
        for a in (md / "areas").glob("*.json"):
            adoc = json.loads(a.read_text(encoding="utf-8"))
            if area_id is not None and a.stem != area_id:
                continue
            if adoc["name"] in stem or (area_id is not None and a.stem == area_id):
                return md.name, a.stem, None
    if area_id is not None:
        return None, area_id, f"override 命中 {area_id} 但 guides 中无对应区域文件"
    return None, None, f"视频名未匹配到任何区域（{stem}）"


def room_to_area(mdir, room_text):
    """VLM room 输出 → 具体区域（标题未标注时自动识别）。

    规则：areas 名称出现在 room 文本中（取最长匹配——防"收容舱段"被
    "舱段"等短名干扰）。无匹配 → None（保持地图级）。
    """
    if not room_text:
        return None
    best_id, best_name = None, ""
    for a in (GUIDES / mdir / "areas").glob("*.json"):
        adoc = json.loads(a.read_text(encoding="utf-8"))
        if adoc["name"] in room_text and len(adoc["name"]) > len(best_name):
            best_id, best_name = a.stem, adoc["name"]
    return best_id


def make_point(area_id, map_id, kind, bbox, frame_no):
    """VLM bbox → 攻略点位（bbox [x1,y1,x2,y2] 0-1000 → 归一化中心）。"""
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return None
    cx = min(1.0, max(0.0, (x1 + x2) / 2 / 1000.0))
    cy = min(1.0, max(0.0, (y1 + y2) / 2 / 1000.0))
    seq = uuid.uuid4().hex[:4]
    return {
        "id": f"{map_id}_{area_id}_{frame_no:04d}_{seq}",
        "name": f"{area_id}·帧{frame_no:04d} 识别点位",
        "type": kind,
        "region": area_id,
        "x": round(cx, 3),
        "y": round(cy, 3),
        "rarity": None,
        "tier": "T1",
        "note": f"来源视频帧 f_{frame_no:04d}.jpg（VLM 自动识别，待人工复核）",
    }


def archive_point(mdir, point, dry_run=False):
    """点位 → maps/<map>/points/<type>.json（去重 by id）。"""
    pdir = GUIDES / mdir / "points"
    pdir.mkdir(parents=True, exist_ok=True)
    fname = {
        "chest": "chests.json",
        "warptrotter": "warptrotters.json",
        "puzzle": "puzzles.json",
    }.get(point["type"], None)
    if fname is None:
        return f"类型 {point['type']} 无归档文件（跳过）"
    target = pdir / fname
    items = []
    if target.exists():
        items = json.loads(target.read_text(encoding="utf-8"))
    ids = {i["id"] for i in items}
    if point["id"] in ids:
        return f"重复跳过 {point['id']}"
    items.append(point)
    if not dry_run:
        target.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return f"归档 {point['id']} -> {target.name}"


def main():
    parser = argparse.ArgumentParser(description="视频 → 攻略归档")
    parser.add_argument("video", help="视频路径")
    parser.add_argument("--max-frames", type=int, default=12, help="最多处理帧数（测试提速）")
    parser.add_argument("--dry-run", action="store_true", help="只报告不写文件")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(f"[FAIL] 视频不存在: {video}")
        return 2

    mdir, area_id, err = resolve_map_area(video.name)
    if err:
        print(f"[FAIL] 归档目标解析失败: {err}")
        return 2
    print(f"[map] 解析 -> {mdir} / {area_id}")

    frames = extract_frames(video)[:args.max_frames]
    print(f"[frames] 抽帧 {len(frames)} 张（限 {args.max_frames}）")

    provider = QwenVLProvider()
    archived = 0
    for i, f in enumerate(frames):
        data = ask_frame(provider, f, i)
        if not data or "chest" not in data:
            continue
        # 特殊任务视频（标题无区域）→ 用 VLM room 输出自动映射具体区域
        point_area = area_id
        if data.get("room"):
            mapped = room_to_area(mdir, str(data["room"]))
            if mapped:
                point_area = mapped
        if data.get("chest", {}).get("found"):
            pt = make_point(point_area, mdir.split("_", 1)[1], "chest",
                            data["chest"].get("bbox"), i)
            if pt:
                msg = archive_point(mdir, pt, args.dry_run)
                if "归档" in msg:
                    archived += 1
                print(f"  f_{i:04d} chest[{point_area}] -> {msg}")
        if data.get("room"):
            print(f"  f_{i:04d} room={data['room']}")

    print(f"[done] 归档 {archived} 条（dry_run={args.dry_run}）"
          f" -> {GUIDES / mdir / 'points'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
