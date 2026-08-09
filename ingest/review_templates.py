import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.vlm_client import QwenVLProvider

TEMPLATE_DIR = Path("knowledge/source/black_tower_test/templates")
BATCH = 6

PROMPT = (
    "这是从游戏画面裁剪出的小图。判断类别（chest实体宝箱 / door门 / landmark地标 / ui图标 / 噪音），"
    "并给出清晰度分 0-100 和可用性（true/false，能否用作游戏内图像匹配模板）。"
    "输出JSON数组，每项: {\"index\": n, \"category\": \"...\", \"clarity\": 0-100, \"usable\": true/false, \"note\": \"简短说明\"}"
)


def main():
    provider = QwenVLProvider()
    files = sorted(TEMPLATE_DIR.glob("*.png"))
    print(f"共 {len(files)} 张候选")
    reviews = []
    failed = []
    for i in range(0, len(files), BATCH):
        batch = files[i:i + BATCH]
        paths = [str(f) for f in batch]
        # Bug 20：单图编码失败只记录，不拖垮整批
        content = []
        for f in batch:
            try:
                mime = "image/png" if f.suffix.lower() == ".png" else "image/jpeg"  # Bug 15
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{_b64(str(f))}"}})
            except Exception as e:
                failed.append(f.name)
                print(f"  编码失败 {f.name}: {e}")
        content.append({"type": "text", "text": PROMPT})
        messages = [{"role": "system", "content": "你是图像模板质检员。"},
                    {"role": "user", "content": content}]
        batch_reviews = []
        try:
            # Bug 16：公开 chat()；Bug 17：先整体 loads，失败再提取
            text = provider.chat(messages, temperature=0)
            try:
                batch_reviews = json.loads(text)
            except Exception:
                start, end = text.find("["), text.rfind("]")
                batch_reviews = json.loads(text[start:end + 1]) if start >= 0 else []
        except Exception as e:
            print(f"批 {i} 失败: {e}")
        if not isinstance(batch_reviews, list):
            batch_reviews = []
        for f, rev in zip(batch, batch_reviews):
            if not isinstance(rev, dict):
                continue
            rev["file"] = f.name
            reviews.append(rev)
            print(f"  {f.name}: {rev}")
        (TEMPLATE_DIR / "reviews.json").write_text(
            json.dumps(reviews, ensure_ascii=False, indent=2), encoding="utf-8")
    if failed:
        print(f"[warn] 编码失败跳过 {len(failed)} 张: {failed}")
    usable = [r for r in reviews if r.get("usable")]
    print(f"\n可用 {len(usable)}/{len(files)}")
    by_cat = {}
    for r in usable:
        by_cat.setdefault(r.get("category"), []).append(r["file"])
    for cat, fs in by_cat.items():
        print(f"  {cat}: {fs}")


def _b64(p):
    import base64
    return base64.b64encode(Path(p).read_bytes()).decode()


if __name__ == "__main__":
    main()
