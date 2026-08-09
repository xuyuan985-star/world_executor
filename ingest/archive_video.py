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
import hashlib
import json
import os
import re
import subprocess
import sys
import time
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
            return mdir, map_id_of(mdir), None
    # Bug 23：攻略库不存在（新装/未导入）→ 明确错误而非 FileNotFoundError
    if not GUIDES.exists():
        return None, None, "攻略库不存在（knowledge/guides/maps）"
    # 3) 遍历所有地图的 areas，找名称匹配的区域文件 → 得地图目录
    for md in sorted(GUIDES.iterdir()):
        if not md.is_dir():
            continue
        for a in (md / "areas").glob("*.json"):
            try:
                adoc = json.loads(a.read_text(encoding="utf-8"))
            except Exception:
                continue
            if area_id is not None and a.stem != area_id:
                continue
            # Bug 16/41：name 缺失不崩；匹配 name + aliases
            for nm in _area_names(adoc):
                if nm and nm in stem:
                    return md.name, a.stem, None
            if area_id is not None and a.stem == area_id:
                return md.name, a.stem, None
    if area_id is not None:
        return None, area_id, f"override 命中 {area_id} 但 guides 中无对应区域文件"
    return None, None, f"视频名未匹配到任何区域（{stem}）"


def _area_names(adoc):
    """区域可匹配名：name + aliases（Bug 41：VLM 可能返回英文/别名）。"""
    names = [adoc.get("name", "")]
    for a in adoc.get("aliases", []) or []:
        names.append(str(a))
    return [n for n in names if n]


def room_to_area(mdir, room_text):
    """VLM room 输出 → 具体区域（标题未标注时自动识别）。

    规则：areas 名称/别名出现在 room 文本中（取最长匹配——防"收容舱段"被
    "舱段"等短名干扰）。无匹配 → None（保持地图级）。
    """
    if not room_text:
        return None
    # Bug 28：mdir 可能含路径分隔——只取目录名拼接到 GUIDES 下
    area_root = GUIDES / Path(mdir).name / "areas"
    if not area_root.exists():
        return None
    best_id, best_name = None, ""
    for a in area_root.glob("*.json"):
        try:
            adoc = json.loads(a.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Bug 41：匹配 name + aliases（VLM 返回英文如 "supply zone" 也能命中）
        for nm in _area_names(adoc):
            if nm and nm in room_text and len(nm) > len(best_name):
                best_id, best_name = a.stem, nm
    return best_id


# 区域英文 id → 中文名（命名可读，对齐视频目录规范）
REGION_CN = {
    "base_zone": "基座舱段", "master_zone": "主控舱段",
    "storage_zone": "收容舱段", "supply_zone": "支援舱段",
    "detention_zone": "禁闭舱段",
    "herta_space_station": "全空间站",
    "jarilo_vi": "雅利洛", "xianzhou_luofu": "仙舟罗浮",
    "penacony": "匹诺康尼", "amphoreus": "翁法罗斯",
}
MAP_CN = {
    "herta_space_station": "黑塔空间站",
    "jarilo_vi": "雅利洛-Ⅵ", "xianzhou_luofu": "仙舟罗浮",
    "penacony": "匹诺康尼", "amphoreus": "翁法罗斯",
}


def map_id_of(mdir):
    """地图目录 → 地图 id：仅剥离 "NN_" 序号前缀，其余保持原名。
    （"02_herta_space_station"→"herta_space_station"；"black_tower"→"black_tower"）"""
    head, sep, tail = mdir.partition("_")
    if not sep:
        return mdir
    return tail if head.isdigit() else mdir


def _file_sha256(path, chunk=1 << 20):
    """Bug 174：视频内容指纹（改名/移动仍可识别重复）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def make_point(area_id, map_id, kind, bbox, frame_no, seq_no=1,
               source_video=None, source_frame=None):
    """VLM bbox → 攻略点位（bbox [x1,y1,x2,y2] 0-1000 → 归一化中心）。

    命名可读：{地图中文}·{区域中文}·宝箱{序号}（对齐视频目录规范）。
    """
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return None
    cx = min(1.0, max(0.0, (x1 + x2) / 2 / 1000.0))
    cy = min(1.0, max(0.0, (y1 + y2) / 2 / 1000.0))
    # Bug 18：稳定 hash 去重（uuid 随机后缀 → 同一视频重归档永远新 id）
    import hashlib
    seq = hashlib.md5(
        f"{map_id}:{area_id}:{frame_no:04d}:{bbox}".encode()
    ).hexdigest()[:4]
    map_cn = MAP_CN.get(map_id, map_id)
    region_cn = REGION_CN.get(area_id, area_id)
    return {
        "id": f"{map_id}_{area_id}_{frame_no:04d}_{seq}",
        "name": f"{map_cn}·{region_cn}·宝箱{seq_no:02d}",
        "type": kind,
        "region": area_id,
        "x": round(cx, 3),
        "y": round(cy, 3),
        # Bug 137：坐标来源分辨率（归一化坐标脱离分辨率无法换算）
        "resolution": [1280, 720],
        # Bug 166：坐标类型声明（归一化 0-1）
        "coordinate_type": "normalized",
        # Bug 167：VLM 自动归档需人工复核（不入正式执行）
        "status": "pending_review",
        # Bug 168：识别置信度（VLM 未输出时 null）
        "confidence": None,
        # Bug 173：来源追溯（哪个视频/哪一帧）
        "source_video": source_video,
        "source_frame": source_frame if source_frame is not None else frame_no,
        "rarity": None,
        "tier": "T1",
        "note": "VLM 自动识别（2遍一致），待人工复核",
    }


def archive_point(mdir, point, dry_run=False):
    """点位 → maps/<map>/points/<type>.json（去重 by id）。

    Bug 180：跨进程文件锁——两个视频同时归档不互相覆盖。
    """
    lock_path = GUIDES / mdir / "points" / ".archive.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        time.sleep(0.2)
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            return "归档锁被占用（另一视频处理中，跳过）"
    try:
        return _archive_point_locked(mdir, point, dry_run)
    finally:
        os.close(lock_fd)
        try:
            lock_path.unlink()
        except OSError:
            pass


def _archive_point_locked(mdir, point, dry_run):
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
        # Bug 17/24：半写入/损坏/非列表（如 {}）的 points 文件按空列表继续
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else []
        except Exception:
            items = []
    # Bug 25：旧版本点位可能缺 id 字段——只按有 id 的条目去重
    ids = {i["id"] for i in items if isinstance(i, dict) and "id" in i}
    if point["id"] in ids:
        return f"重复跳过 {point['id']}"
    items.append(point)
    if not dry_run:
        # Bug 42：原子写——临时文件替换（防中断写坏整个 points JSON）
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(target)
        # Bug 91：点位库版本元信息（地图更新/重归档时可追溯）
        meta = pdir / "points_meta.json"
        meta_tmp = meta.with_name("points_meta.json.tmp")
        meta_tmp.write_text(json.dumps(
            {"version": "1.1", "game_patch": "latest",
             "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False, indent=2), encoding="utf-8")
        meta_tmp.replace(meta)
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

    # Bug 174：重复视频检测（内容 sha256——文件改名也能识别已处理）
    video_hash = _file_sha256(video)
    done_log = ROOT / "ingest" / "raw" / "archived_videos.json"
    done_map = {}
    if done_log.exists():
        try:
            done_map = json.loads(done_log.read_text(encoding="utf-8"))
        except Exception:
            done_map = {}
    if video_hash in done_map:
        print(f"[SKIP] 视频已处理过（{done_map[video_hash]}）——防重复分析")
        return 0

    mdir, area_id, err = resolve_map_area(video.name)
    if err:
        print(f"[FAIL] 归档目标解析失败: {err}")
        return 2
    print(f"[map] 解析 -> {mdir} / {area_id}")

    frames = extract_frames(video)[:args.max_frames]
    print(f"[frames] 抽帧 {len(frames)} 张（限 {args.max_frames}）")

    provider = QwenVLProvider()
    archived = 0
    # Bug 178：VLM 结果分类统计（NO_CHEST / INVALID_JSON / INVALID_BOX / LOW_CONFIDENCE）
    stats = {"no_chest": 0, "invalid_json": 0, "invalid_box": 0,
             "low_confidence": 0, "archived": 0}
    # Bug 176：分析中间产物目录（误判可人工复核）
    artifact_dir = ROOT / "ingest" / "raw" / "analysis" / mdir
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        data = ask_frame(provider, f, i)
        if data.get("error"):
            stats["invalid_json"] += 1
            print(f"  f_{i:04d} VLM 异常: {data['error'][:80]}")
            continue
        if not data or "chest" not in data:
            stats["no_chest"] += 1
            continue
        # Bug 176：保存原始响应（复核依据）
        resp_file = artifact_dir / f"{f.stem}_response.json"
        resp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        # 特殊任务视频（标题无区域）→ 用 VLM room 输出自动映射具体区域
        point_area = area_id
        if data.get("room"):
            mapped = room_to_area(mdir, str(data["room"]))
            if mapped:
                point_area = mapped
        # Bug 26：VLM 格式不稳定——chest 可能是 dict / True / str，逐一防护
        chest = data.get("chest")
        if isinstance(chest, dict) and chest.get("found"):
            # Bug 116：VLM 置信度过滤（低于门槛不入库，防低可信点位）
            conf = chest.get("confidence")
            if conf is not None:
                try:
                    if float(conf) < 0.8:
                        stats["low_confidence"] += 1
                        print(f"  f_{i:04d} chest 置信 {conf} < 0.8（拒绝入库）")
                        continue
                except (TypeError, ValueError):
                    pass
            if point_area is None:
                print("  f_{:04d} chest 但区域未解析（跳过，防 region=null）".format(i))
                continue
            pt = make_point(point_area, map_id_of(mdir), "chest",
                            chest.get("bbox"), i,
                            source_video=video.name, source_frame=i)
            if not pt:
                # Bug 27/178：bbox 缺失/非法 → 分类统计（可查为何少点位）
                stats["invalid_box"] += 1
                print(f"  f_{i:04d} chest bbox 无效或缺失（跳过）")
                continue
            msg = archive_point(mdir, pt, args.dry_run)
            if "归档" in msg:
                stats["archived"] += 1
                archived += 1
            print(f"  f_{i:04d} chest[{point_area}] -> {msg}")
        if data.get("room"):
            print(f"  f_{i:04d} room={data['room']}")

    # Bug 174：记录已处理视频（内容 hash）
    if not args.dry_run:
        done_map[video_hash] = str(video)
        done_log.parent.mkdir(parents=True, exist_ok=True)
        done_log.write_text(json.dumps(done_map, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    print(f"[done] 归档 {archived} 条（dry_run={args.dry_run}）"
          f" -> {GUIDES / mdir / 'points'}")
    print(f"[stats] {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
