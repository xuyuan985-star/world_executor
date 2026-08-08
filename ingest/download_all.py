import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import bilibili

BVID = "BV1YM4y1a7wf"
PAGES = list(range(2, 9))


def main():
    title, pages = bilibili.pages_of(BVID)
    for i in PAGES:
        page, cid, part, dur = pages[i]
        name = f"三重权限_P{page}_{part.split(' ')[0]}"
        path = bilibili.OUT_DIR / f"{name}.mp4"
        if path.exists():
            print(f"[skip] {path}")
            continue
        print(f"[P{page}] {part} 下载中")
        try:
            bilibili.download(BVID, out_name=name, qn=32, p_index=i)
        except Exception as e:
            print(f"[P{page}] 失败: {e}")


if __name__ == "__main__":
    main()
