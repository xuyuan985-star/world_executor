import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

# Bug 55：目录基于仓库根绝对定位（任意 cwd 启动不写错位置）
ROOT = Path(__file__).resolve().parent.parent
CAPTURE_DIR = ROOT / "ingest" / "raw" / "frames" / "capture"
TEMPLATE_DIR = ROOT / "knowledge" / "source" / "black_tower_test" / "templates"


def norm_box(box, w, h, pad=8):
    if not box or len(box) < 4:
        return None
    try:
        nums = [float(v) for v in box[:4]]
    except (TypeError, ValueError):
        return None
    x1, y1, x2, y2 = [n / 1000.0 * (w if i % 2 == 0 else h) for i, n in enumerate(nums)]
    return [max(0, int(x1) - pad), max(0, int(y1) - pad), min(w, int(x2) + pad), min(h, int(y2) + pad)]


def crop(frames, results, out_prefix, kind_name):
    out = []
    for r in results:
        data = r.get("data", {})
        # 审查 P1：PROMPT v3 输出键为 chest/door/landmark（对象含 found/bbox）
        boxes = data.get(kind_name)
        if not boxes or boxes == "none":
            continue
        if isinstance(boxes, dict):
            # v3 结构：{"found": bool, "bbox": [x1,y1,x2,y2]}
            if boxes.get("found") is False:
                continue
            boxes = [boxes.get("bbox") or boxes]
        if isinstance(boxes, list):
            for b in boxes:
                if isinstance(b, str):
                    continue
                if isinstance(b, dict):
                    # 兼容旧 bbox_2d/label 结构与 v3 bbox 直给
                    box = b.get("bbox_2d") or b.get("bbox") or b.get("box")
                    label = b.get("label") or b.get("name") or "unknown"
                else:
                    box = b
                    label = "unknown"
                if not box or isinstance(box, str):
                    continue
                img_path = CAPTURE_DIR / r["frame"]
                if not img_path.exists():
                    continue
                # Bug 56：with 打开防文件句柄泄漏（批量裁剪可能锁文件）
                with Image.open(img_path) as img:
                    w, h = img.size
                    n = norm_box(box, w, h)
                    if not n:
                        continue
                    x1, y1, x2, y2 = n
                    if x2 - x1 < 10 or y2 - y1 < 10:
                        continue
                    crop_img = img.crop((x1, y1, x2, y2))
                    name = f"{out_prefix}_{r['frame']}_{kind_name}_{len(out)}.png"
                    crop_img.save(TEMPLATE_DIR / name)
                out.append({"file": name, "frame": r["frame"], "label": label, "box": box})
    return out


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    results = json.loads((CAPTURE_DIR / "results.json").read_text(encoding="utf-8"))
    frames = results
    kinds = {
        "chest": ("chest", "宝箱"),
        "door": ("door", "门"),
        "landmark": ("landmark", "地标"),
    }
    manifest = {}
    for key, (prefix, label) in kinds.items():
        crops = crop(frames, results, prefix, key)
        print(f"[{label}] 裁剪 {len(crops)} 张")
        manifest[label] = crops
    (CAPTURE_DIR / "crop_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Bug 118：模板库哈希校验清单（图片被替换/损坏可检测）
    hashes = {}
    for p in sorted(TEMPLATE_DIR.glob("*.png")):
        hashes[p.name] = _sha256(p)
    (TEMPLATE_DIR / "templates_manifest.json").write_text(
        json.dumps({"version": 1, "hashes": hashes}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"输出目录: {TEMPLATE_DIR}（模板哈希清单 {len(hashes)} 张）")


if __name__ == "__main__":
    main()
