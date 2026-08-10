"""点位核查工具：网站真实点位（yxhhdl 地图工具） vs 我们地图集。

用法：python tools/verify_points.py [map_dir]
输出：每区域 真实/已有/骨架/缺口 + 覆盖率报告。
数据源：www.onebiji.com ys_js/ch-bhsrd_categories.js（marker→dt/数量）
+ ch-marker-{id}-loc.js（真实点位数）。
"""
import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://www.onebiji.com/hykb/hykb_tools/bhsrd/star/ys_js/"

# dt → 我们 area id（与骨架生成映射一致）
DT_AREA = {
    "dt1": ("02_herta_space_station", "master_zone"), "dt2": ("02_herta_space_station", "base_zone"),
    "dt3": ("02_herta_space_station", "storage_zone"), "dt4": ("02_herta_space_station", "storage_zone"),
    "dt5": ("02_herta_space_station", "storage_zone"), "dt6": ("02_herta_space_station", "supply_zone"),
    "dt7": ("02_herta_space_station", "supply_zone"), "dt42": ("02_herta_space_station", "detention_zone"),
    "dt43": ("02_herta_space_station", "detention_zone"), "dt44": ("02_herta_space_station", "detention_zone"),
    "dt8": ("03_jarilo_vi", "administration_district"), "dt9": ("03_jarilo_vi", "administration_district"),
    "dt10": ("03_jarilo_vi", "suburban_snowfield"), "dt11": ("03_jarilo_vi", "edge_passage"),
    "dt12": ("03_jarilo_vi", "iron_guard_zone"), "dt13": ("03_jarilo_vi", "echo_corridor"),
    "dt14": ("03_jarilo_vi", "everwinter_hill"), "dt15": ("03_jarilo_vi", "rocktown"),
    "dt16": ("03_jarilo_vi", "big_mine"), "dt17": ("03_jarilo_vi", "rivet_town"),
    "dt18": ("03_jarilo_vi", "rivet_town"), "dt19": ("03_jarilo_vi", "mechanical_landing"),
    "dt20": ("03_jarilo_vi", "mechanical_landing"),
    "dt21": ("04_xianzhou_luofu", "starskiff_haven"), "dt22": ("04_xianzhou_luofu", "cloudford"),
    "dt23": ("04_xianzhou_luofu", "cloudford"), "dt24": ("04_xianzhou_luofu", "fluxing_starport"),
    "dt25": ("04_xianzhou_luofu", "changle_hall"), "dt26": ("04_xianzhou_luofu", "divination_commission"),
    "dt27": ("04_xianzhou_luofu", "divination_commission"), "dt28": ("04_xianzhou_luofu", "artisanship_commission"),
    "dt29": ("04_xianzhou_luofu", "alchemy_commission"), "dt30": ("04_xianzhou_luofu", "alchemy_commission"),
    "dt31": ("04_xianzhou_luofu", "scalegorge_waterscape"), "dt32": ("04_xianzhou_luofu", "jinren_alley"),
    "dt41": ("04_xianzhou_luofu", "fyxestroll_garden"), "dt70": ("04_xianzhou_luofu", "shackling_prison"),
    "dt71": ("04_xianzhou_luofu", "crossing_fires"),
    "dt45": ("05_penacony", "hotel_reality"), "dt46": ("05_penacony", "golden_hour"),
    "dt47": ("05_penacony", "dreams_edge"), "dt48": ("05_penacony", "childs_dream"),
    "dt49": ("05_penacony", "hotel_dream"), "dt50": ("05_penacony", "childs_dream"),
    "dt51": ("05_penacony", "hotel_dream"), "dt52": ("05_penacony", "hotel_dream"),
    "dt53": ("05_penacony", "hotel_dream"), "dt54": ("05_penacony", "hotel_dream"),
    "dt55": ("05_penacony", "hotel_dream"), "dt56": ("05_penacony", "dewlight_pavilion"),
    "dt57": ("05_penacony", "dewlight_pavilion"), "dt58": ("05_penacony", "dewlight_pavilion"),
    "dt59": ("05_penacony", "dewlight_pavilion"), "dt60": ("05_penacony", "dewlight_pavilion"),
    "dt61": ("05_penacony", "clock_studios"), "dt62": ("05_penacony", "clock_studios"),
    "dt63": ("05_penacony", "scorchsand_venue"), "dt64": ("05_penacony", "scorchsand_venue"),
    "dt65": ("05_penacony", "scorchsand_venue"), "dt66": ("05_penacony", "scorchsand_venue"),
    "dt67": ("05_penacony", "dreamflux_reef"), "dt68": ("05_penacony", "grand_theater"),
    "dt69": ("05_penacony", "radiant_feldspar"), "dt72": ("05_penacony", "paperfold_university"),
    "dt101": ("05_penacony", "oak_dream"),
    "dt73": ("06_amphoreus", "hanging_ruins"), "dt74": ("06_amphoreus", "hanging_forge"),
    "dt75": ("06_amphoreus", "hanging_forge"), "dt76": ("06_amphoreus", "hanging_forge"),
    "dt77": ("06_amphoreus", "okhema_eternal"), "dt78": ("06_amphoreus", "janusopolis_abyss"),
    "dt79": ("06_amphoreus", "genesis_eddy"), "dt80": ("06_amphoreus", "grove_whisper"),
    "dt81": ("06_amphoreus", "grove_whisper"), "dt82": ("06_amphoreus", "grove_whisper"),
    "dt83": ("06_amphoreus", "janusopolis_oracle"), "dt84": ("06_amphoreus", "janusopolis_oracle"),
    "dt85": ("06_amphoreus", "janusopolis_oracle"), "dt86": ("06_amphoreus", "janusopolis_oracle"),
    "dt87": ("06_amphoreus", "styxia_dragon"), "dt88": ("06_amphoreus", "dawn_cliff_senate"),
    "dt89": ("06_amphoreus", "okhema_sunken"), "dt90": ("06_amphoreus", "eye_twilight_fort"),
    "dt91": ("06_amphoreus", "dawn_cliff_shrine"), "dt92": ("06_amphoreus", "eye_twilight_castle"),
    "dt93": ("06_amphoreus", "eerie_manor"), "dt94": ("06_amphoreus", "styxia_dragon"),
    "dt95": ("06_amphoreus", "grove_radiant"), "dt96": ("06_amphoreus", "nameless_titan_tomb"),
    "dt97": ("06_amphoreus", "time_ruins"), "dt98": ("06_amphoreus", "time_ruins"),
    "dt99": ("06_amphoreus", "time_ruins"), "dt100": ("06_amphoreus", "nameless_titan_tomb"),
    "dt103": ("07_dream_paradise", "planar_city"), "dt104": ("07_dream_paradise", "drawing_academy"),
    "dt105": ("07_dream_paradise", "pigeon_river"), "dt106": ("07_dream_paradise", "pigeon_river"),
    "dt107": ("07_dream_paradise", "pigeon_river"), "dt108": ("07_dream_paradise", "pigeon_river"),
    "dt109": ("07_dream_paradise", "drawing_academy"), "dt110": ("07_dream_paradise", "drawing_academy"),
    "dt111": ("07_dream_paradise", "drawing_academy"), "dt112": ("07_dream_paradise", "drawing_academy"),
    "dt113": ("07_dream_paradise", "drawing_academy"), "dt114": ("07_dream_paradise", "planar_city"),
    "dt115": ("07_dream_paradise", "planar_city"), "dt116": ("07_dream_paradise", "planar_city"),
    "dt117": ("07_dream_paradise", "planar_city"), "dt102": ("07_dream_paradise", "worlds_end_tavern"),
    "dt118": ("07_dream_paradise", "worlds_end_tavern"), "dt119": ("07_dream_paradise", "worlds_end_tavern"),
    "dt120": ("07_dream_paradise", "worlds_end_tavern"), "dt121": ("07_dream_paradise", "worlds_end_tavern"),
    "dt122": ("07_dream_paradise", "worlds_end_tavern"), "dt123": ("07_dream_paradise", "pearl_star_building"),
    "dt124": ("07_dream_paradise", "pearl_star_building"), "dt125": ("07_dream_paradise", "pearl_star_building"),
    "dt126": ("07_dream_paradise", "cloud_view_station"), "dt127": ("07_dream_paradise", "cloud_view_station"),
    "dt128": ("07_dream_paradise", "cloud_view_station"), "dt129": ("07_dream_paradise", "cloud_view_station"),
    "dt130": ("07_dream_paradise", "cloud_view_station"), "dt131": ("07_dream_paradise", "cloud_view_station"),
    "dt132": ("07_dream_paradise", "pearl_star_building"), "dt133": ("07_dream_paradise", "pearl_star_building"),
    "dt134": ("07_dream_paradise", "ocean_city"), "dt135": ("07_dream_paradise", "ocean_tv_tower"),
    "dt136": ("07_dream_paradise", "ocean_tv_tower"), "dt137": ("07_dream_paradise", "ocean_tv_tower"),
    "dt138": ("07_dream_paradise", "ocean_tv_tower"), "dt139": ("07_dream_paradise", "ocean_tv_tower"),
    "dt140": ("07_dream_paradise", "ocean_tv_tower"), "dt141": ("07_dream_paradise", "ocean_city"),
    "dt142": ("07_dream_paradise", "ocean_city"), "dt143": ("07_dream_paradise", "ocean_city"),
}

# 战利品类名称匹配
CHEST_NAMES = ("战利品", "宝箱")


def fetch_site_counts():
    """抓网站每 dt 的真实战利品数（loc 文件逐点统计——比 loc_num 更准）。"""
    r = requests.get(BASE + "ch-bhsrd_categories.js", timeout=60)
    text = r.content.decode("gbk", errors="replace")
    m = re.search(r"func\((\{.*\})\)\s*$", text, re.DOTALL)
    markers = json.loads(m.group(1))
    dt_counts = {}
    for key, mk in markers.items():
        if not any(k in mk.get("name", "") for k in CHEST_NAMES):
            continue
        dt = mk.get("type", "")
        url = BASE + f"ch-marker-{mk['id']}-loc.js"
        try:
            rr = requests.get(url, timeout=60)
            if rr.status_code != 200:
                continue
            lt = rr.content.decode("gbk", errors="replace")
            mm = re.search(r"func_loc_\d+\((\{.*\})\)\s*$", lt, re.DOTALL)
            if mm:
                locs = json.loads(mm.group(1))
                dt_counts[dt] = dt_counts.get(dt, 0) + len(locs)
        except Exception:
            continue
    return dt_counts


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    site = fetch_site_counts()
    print(f"网站抓取 dt 数: {len(site)}，总点位数: {sum(site.values())}")

    rows = []
    per_area_site = {}
    for dt, (mdir, area) in DT_AREA.items():
        n = site.get(dt, 0)
        if n <= 0:
            continue
        per_area_site.setdefault((mdir, area), 0)
        per_area_site[(mdir, area)] += n

    total_real = total_have = total_empty = 0
    for (mdir, area), need in sorted(per_area_site.items()):
        if target and mdir != target:
            continue
        pts = ROOT / "knowledge" / "guides" / "maps" / mdir / "points" / "chests.json"
        have = 0
        empty = 0
        if pts.exists():
            data = json.loads(pts.read_text(encoding="utf-8"))
            have = sum(1 for c in data if c.get("region") == area
                       and c.get("status") != "empty")
            empty = sum(1 for c in data if c.get("region") == area
                        and c.get("status") == "empty")
        pct = have / need * 100 if need else 0
        rows.append(f"{mdir}/{area}: 真实{need} 已有{have} 骨架{empty} "
                    f"覆盖率{pct:.0f}%")
        total_real += need
        total_have += have
        total_empty += empty
    out = "\n".join(rows)
    if not target:
        out += (f"\n\n=== 汇总: 真实{total_real} 已有真点位{total_have} "
                f"(覆盖率{total_have/total_real*100:.0f}%) 骨架{total_empty} ===")
    open("C:/Users/xuyua/AppData/Local/Temp/opencode/verify_report.txt", "w",
         encoding="utf-8").write(out)
    print(out)


if __name__ == "__main__":
    main()
