"""guides 攻略数据加载（GUI 联动：指挥台目标 = 攻略存档真实点位）。

knowledge/guides/maps/<map_dir>/points/*.json → 目标列表。
"""
import json
from pathlib import Path

GUIDES = Path(__file__).resolve().parent / "guides" / "maps"

# 自定义地图（录制轨迹平级展示）：08_custom 点位动态同步自 trajectories/
CUSTOM_MAP = "08_custom"


def sync_custom_map(enabled=None):
    """同步录制轨迹 → 自定义地图点位（世界图/指挥台自动平级展示）。

    每个轨迹文件 = 一个点位（id=文件名去扩展名，trajectory 指向原文件）。
    enabled: 可选启用集（轨迹文件名列表）——None=全部启用；
    未启用的轨迹文件保留在 trajectories/ 但不作为目标展示。
    录制保存后调用即可——两边读同一 GUIDES 目录，动态一致。
    """
    import json as _json
    traj_dir = Path(__file__).resolve().parent.parent / "knowledge" / "trajectories"
    md = GUIDES / CUSTOM_MAP
    (md / "points").mkdir(parents=True, exist_ok=True)
    (md / "areas").mkdir(parents=True, exist_ok=True)
    # 区域文件（数据完整性校验需要——自定义地图统一"自定义"区域）
    (md / "areas" / "custom.json").write_text(
        _json.dumps({"name": "自定义", "id": "custom"},
                    ensure_ascii=False, indent=1), encoding="utf-8")
    (md / "map.json").write_text(
        _json.dumps({"id": CUSTOM_MAP, "name": "自定义"},
                    ensure_ascii=False, indent=1), encoding="utf-8")
    items = []
    if traj_dir.exists():
        for tf in sorted(traj_dir.glob("*.json")):
            if enabled is not None and tf.name not in enabled:
                continue
            items.append({
                "id": tf.stem,
                "name": tf.stem,  # 直接文件名（自定义-1 / traj_xxx），可读可排序
                "region": "custom",  # 区域 id 与其他地图一致（英文 id）
                "type": "chest",
                "trajectory": tf.name,
            })
    (md / "points" / "chests.json").write_text(
        _json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(items)


def custom_enabled_names():
    """当前自定义地图启用的轨迹文件名集合（读 08_custom 点位）。"""
    import json as _json
    try:
        pf = GUIDES / CUSTOM_MAP / "points" / "chests.json"
        if not pf.exists():
            return set()
        pts = _json.loads(pf.read_text(encoding="utf-8"))
        return {p.get("trajectory") for p in pts if p.get("trajectory")}
    except Exception:
        return set()

POINT_TYPES = {
    "chests.json": "chest",
    "warptrotters.json": "warptrotter",
    "puzzles.json": "puzzle",
    "books.json": "book",
    "enemies.json": "enemy",
    "achievements.json": "achievement",
    "quests.json": "quest",
    "shops.json": "shop",
    "anchors.json": "anchor",
}


def load_guide_targets(map_dir="02_herta_space_station", types=None):
    """读攻略存档点位 → 目标列表 [{id, name, region, type}]。

    types=None → 全部；否则白名单（如 ["chest"]）。
    """
    md = GUIDES / map_dir
    if not md.exists():
        return []
    want = set(types) if types else set(POINT_TYPES.values())
    targets = []
    for fname, ptype in POINT_TYPES.items():
        if ptype not in want:
            continue
        p = md / "points" / fname
        if not p.exists():
            continue
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for it in items:
            targets.append({
                "id": it.get("id", ""),
                "name": it.get("name") or it.get("id"),
                "region": it.get("region", ""),
                "type": ptype,
                # 轨迹字段透传（自定义地图点位→指挥台→执行链 trajectory 步骤）
                "trajectory": it.get("trajectory"),
            })
    return targets


def load_guide_regions(map_dir="02_herta_space_station"):
    """区域列表 [{id, name}]（供指挥台展示区域名）。"""
    md = GUIDES / map_dir
    if not md.exists():
        return []
    out = []
    for a in sorted((md / "areas").glob("*.json")):
        try:
            adoc = json.loads(a.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({"id": a.stem, "name": adoc.get("name", a.stem)})
    return out
