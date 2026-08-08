import json
import sys
import urllib.parse
import urllib.request

BVID = "BV1YM4y1a7wf"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
REFERER = "https://www.bilibili.com/"


def http_get(url, referer=REFERER, cookie=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": referer,
        "Cookie": cookie or "",
        "Origin": "https://www.bilibili.com",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_pages():
    data = http_get(f"https://api.bilibili.com/x/web-interface/view?bvid={BVID}")
    pages = data["data"]["pages"]
    return [(p["page"], p["cid"], p["part"], p["duration"]) for p in pages]


def get_playurl(cid, qn=80, cookie=None):
    q = urllib.parse.urlencode({"bvid": BVID, "cid": cid, "qn": qn, "fnver": 0, "fnval": 16})
    return http_get(f"https://api.bilibili.com/x/player/playurl?{q}", cookie=cookie)


def main():
    cookie = sys.argv[1] if len(sys.argv) > 1 else None
    label = "WITH_COOKIE" if cookie else "NO_COOKIE"
    pages = get_pages()
    print(f"[{label}] 共 {len(pages)} 个分P:")
    for page, cid, part, dur in pages:
        print(f"  P{page} cid={cid} dur={dur}s {part}")

    page, cid, part, dur = pages[0]
    data = get_playurl(cid, cookie=cookie)
    d = data.get("data", {})
    desc = d.get("quality", "?")
    dash = d.get("dash")
    durl = d.get("durl")
    if durl:
        print(f"[{label}] P1 可用: quality={desc}, {len(durl)} 个分片, 最高 {max(x.get('size', 0) for x in durl) // 1024 // 1024}MB")
    elif dash:
        vids = [v["id"] for v in dash["video"]]
        audio = dash.get("audio", [])
        print(f"[{label}] P1 dash 可用: quality={desc}, 视频流 {len(vids)} 个: {vids[:6]}... 音频流 {len(audio)} 个")
    else:
        print(f"[{label}] P1 失败: {json.dumps(d, ensure_ascii=False)[:300]}")


if __name__ == "__main__":
    main()
