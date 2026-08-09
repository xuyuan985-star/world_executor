import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
REFERER = "https://www.bilibili.com/"
# Bug 20：输出目录基于仓库根绝对定位（任意 cwd 启动不写错位置）
OUT_DIR = Path(__file__).resolve().parent.parent / "ingest" / "raw" / "videos"


class BiliError(Exception):
    pass


def get_cookie():
    # Bug 21：settings 可能无 get()（配置对象结构变化不崩）
    return getattr(settings, "BILIBILI_COOKIE", "")


def http_get(url, cookie=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": REFERER,
        "Origin": "https://www.bilibili.com",
        "Cookie": cookie or get_cookie(),
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pages_of(bvid):
    data = http_get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    if data.get("code") != 0:
        raise BiliError(f"view API 失败: {data.get('message')}")
    d = data["data"]
    title = d["title"]
    pages = [(p["page"], p["cid"], p["part"], p["duration"]) for p in d["pages"]]
    return title, pages


def playurl(bvid, cid, qn=80, cookie=None):
    q = urllib.parse.urlencode({"bvid": bvid, "cid": cid, "qn": qn, "fnval": 16, "fourk": 1})
    data = http_get(f"https://api.bilibili.com/x/player/playurl?{q}", cookie=cookie)
    if data.get("code") != 0:
        raise BiliError(f"playurl 失败: {data.get('message')}")
    d = data.get("data") or {}
    return d


def pick_stream(streams, want):
    for v in streams:
        if v["id"] == want:
            return v
    return max(streams, key=lambda v: v["id"])


def download(bvid, out_name=None, qn=80, p_index=0, cookie=None):
    cookie = cookie if cookie is not None else get_cookie()
    if not cookie:
        print("[warn] 无 cookie，可能只能拿到 480p 及以下")
    title, pages = pages_of(bvid)
    if not pages:
        raise BiliError("无分P")
    page, cid, part, dur = pages[p_index]
    out_name = out_name or f"{bvid}_P{page}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    final = OUT_DIR / f"{out_name}.mp4"
    if final.exists():
        print(f"已存在: {final}")
        return final

    d = playurl(bvid, cid, qn=qn, cookie=cookie)
    dash = d.get("dash")
    if not dash:
        raise BiliError(f"无 dash 流（quality={d.get('quality')}）")

    v = pick_stream(dash["video"], qn if qn in [v["id"] for v in dash["video"]] else max(v["id"] for v in dash["video"]))
    a = max(dash["audio"], key=lambda s: s["id"])
    vfile = OUT_DIR / f"{out_name}.video.m4s"
    afile = OUT_DIR / f"{out_name}.audio.m4s"

    print(f"[P{page}] {part} ({dur}s) quality={v['id']} 下载中 ...")
    for f, url in ((vfile, v["baseUrl"] or v["base_url"]), (afile, a["baseUrl"] or a["base_url"])):
        if f.exists():
            continue
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": REFERER, "Cookie": cookie})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp, open(f, "wb") as fh:
                total = int(resp.headers.get("Content-Length", 0))
                done = 0
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // total
                        print(f"    {f.name} {pct}%", end="\r")
        except Exception as e:
            # Bug 22：下载中断不留残缺 m4s（下次重试从零开始）
            f.unlink(missing_ok=True)
            raise BiliError(f"下载失败 {f.name}: {type(e).__name__}: {e}")
        print(f"    {f.name} {total // 1024 // 1024}MB 完成")

    # Bug 22：合并先写临时文件，成功才原子改名——坏 mp4 不冒充成品
    final_tmp = final.with_name(final.name + ".tmp")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(vfile), "-i", str(afile),
            "-c", "copy", str(final_tmp),
        ], check=True)
    except Exception as e:
        final_tmp.unlink(missing_ok=True)
        vfile.unlink(missing_ok=True)
        afile.unlink(missing_ok=True)
        raise BiliError(f"ffmpeg 合并失败: {type(e).__name__}: {e}")
    final_tmp.rename(final)
    vfile.unlink()
    afile.unlink()
    print(f"合成完成: {final} ({final.stat().st_size // 1024 // 1024}MB)")
    return final


def main():
    import argparse

    parser = argparse.ArgumentParser(description="B站分P视频下载器（dash + ffmpeg 合成）")
    parser.add_argument("bvid", help="BV号")
    parser.add_argument("--out", default=None, help="输出名（默认 BV号_P{page}）")
    parser.add_argument("--qn", type=int, default=80, help="目标码率 id（80=1080p, 64=720p, 32=480p）")
    parser.add_argument("--page", type=int, default=0, help="分P索引（0 起）")
    parser.add_argument("--cookie", default=None, help="B站 cookie（SESSDATA=...）")
    args = parser.parse_args()
    download(args.bvid, out_name=args.out, qn=args.qn, p_index=args.page, cookie=args.cookie)


if __name__ == "__main__":
    main()
