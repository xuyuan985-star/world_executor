import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.knowledge_loader import KnowledgePackage

ALLOWED_STEP_TYPES = {"move", "visual_guided_move", "interact", "portal", "verify", "wait", "state_check"}


def validate(pkg: KnowledgePackage, verbose=True):
    errors = []
    warnings = []

    if pkg.rooms is None:
        errors.append("缺少 rooms.json")
    else:
        if "spawn_room" not in pkg.rooms:
            errors.append("rooms.json 缺少 spawn_room")
        rooms = pkg.rooms.get("rooms", [])
        if not rooms:
            errors.append("rooms.json 的 rooms 为空")
        for r in rooms:
            if "id" not in r:
                errors.append("rooms.json 中存在缺少 id 的房间")

    if pkg.chests is None:
        errors.append("缺少 chests.json")
    elif not isinstance(pkg.chests, list):
        # Bug 52：chests 非 list（如 {} 或字符串）→ 明确格式错误而非遍历 key
        errors.append(f"chests.json 格式错误（应为列表，实际 {type(pkg.chests).__name__}）")
    else:
        room_ids = pkg.room_ids()
        for c in pkg.chests:
            cid = c.get("id")
            if not cid:
                errors.append("chests.json 中存在缺少 id 的宝箱")
                continue
            # Bug 93：点位字段 schema 校验（坐标/类型缺失提前暴露，不运行中崩）
            # null 坐标合法（mock/逻辑测试点位）；缺失 → warning；非数值/越界 → error
            for field in ("x", "y"):
                if field not in c or c[field] is None:
                    warnings.append(f"宝箱 {cid} 无 {field} 坐标（mock/逻辑测试点位）")
                    continue
                try:
                    v = float(c[field])
                    if not (0.0 <= v <= 1.0):
                        errors.append(f"宝箱 {cid} 的 {field}={v} 超出归一化范围 [0,1]")
                except (TypeError, ValueError):
                    errors.append(f"宝箱 {cid} 的 {field} 非数值: {c[field]!r}")
            if c.get("room") not in room_ids:
                errors.append(f"宝箱 {cid} 的 room '{c.get('room')}' 不存在")
            if c.get("template") and not pkg.template_exists(c["template"]):
                errors.append(f"宝箱 {cid} 的模板图片缺失: templates/{c['template']}")
            wf = pkg.workflow(cid)
            if wf is None:
                errors.append(f"宝箱 {cid} 缺少 workflow: workflows/{cid}.json")
            elif wf.get("protocol") != "1.3":
                errors.append(f"宝箱 {cid} 的 workflow 协议版本应为 1.3")

    room_ids = pkg.room_ids()
    for p in pkg.portals or []:
        pid = p.get("id")
        if not pid:
            errors.append("portals.json 中存在缺少 id 的传送门")
            continue
        if p.get("from") not in room_ids:
            errors.append(f"传送门 {pid} 的 from '{p.get('from')}' 不存在")
        if p.get("to") not in room_ids:
            errors.append(f"传送门 {pid} 的 to '{p.get('to')}' 不存在")
        if p.get("trigger", {}).get("template") and not pkg.template_exists(p["trigger"]["template"]):
            errors.append(f"传送门 {pid} 的触发模板缺失: templates/{p['trigger']['template']}")

    for l in pkg.landmarks or []:
        if l.get("room") not in room_ids:
            errors.append(f"地标 {l.get('id')} 的 room '{l.get('room')}' 不存在")
        if l.get("template") and not pkg.template_exists(l["template"]):
            errors.append(f"地标 {l.get('id')} 的模板图片缺失: templates/{l['template']}")

    for c in pkg.chests or []:
        wf = pkg.workflow(c["id"]) if isinstance(c, dict) and c.get("id") else None
        if not wf:
            continue
        for i, step in enumerate(wf.get("steps", [])):
            # Bug 53：steps 含 null/非对象 → 明确报错而非 AttributeError
            if not isinstance(step, dict):
                errors.append(f"{c.get('id')} workflow 第 {i} 步不是对象: {type(step).__name__}")
                continue
            if step.get("type") not in ALLOWED_STEP_TYPES:
                errors.append(f"{c['id']} workflow 第 {i} 步类型非法: {step.get('type')}")
            if step.get("type") == "portal" and step.get("portal_id"):
                if pkg.portal(step["portal_id"]) is None:
                    errors.append(f"{c['id']} workflow 引用不存在的传送门: {step['portal_id']}")
                else:
                    portal = pkg.portal(step["portal_id"])
                    if portal and portal.get("to") != c.get("room"):
                        warnings.append(f"{c['id']} 经传送门 {step['portal_id']} 到达 {portal.get('to')}，但宝箱在 {c.get('room')}")

    if verbose:
        for w in warnings:
            print(f"[WARN] {w}")
        for e in errors:
            print(f"[ERROR] {e}")
        print(f"== validate: {len(errors)} error(s), {len(warnings)} warning(s) ==")
    return errors, warnings


def main():
    if len(sys.argv) < 2:
        print("用法: python -m ingest.compiler.validate_graph <knowledge_dir>")
        sys.exit(2)
    pkg = KnowledgePackage(Path(sys.argv[1]))
    errors, _ = validate(pkg)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
