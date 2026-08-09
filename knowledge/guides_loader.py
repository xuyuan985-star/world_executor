"""guides 攻略数据加载（GUI 联动：指挥台目标 = 攻略存档真实点位）。

knowledge/guides/maps/<map_dir>/points/*.json → 目标列表。
"""
import json
from pathlib import Path

GUIDES = Path(__file__).resolve().parent / "guides" / "maps"

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
