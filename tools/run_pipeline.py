"""一键预处理管线（视频 → 攻略知识包）——解决"预处理瘫痪"（部件全活但
无一键入口）。

流程（每步标注 大模型视觉 / 预设程序）：
  1. [预设] 扫描 ingest/raw/videos 攻略视频
  2. [预设] ffmpeg 抽帧（每 2s，1280 宽）——capture_frames.extract_frames
  3. [大模型视觉] VLM 逐帧检测宝箱/门/地标 bbox——capture_frames.ask_frame
  4. [预设] 按 bbox 裁剪模板——crop_templates.crop
  5. [预设] 知识包校验——validate_graph.validate
输出：knowledge/source/<pkg>/（chests.json/workflows/templates）

用法：python tools/run_pipeline.py [视频目录] [--max-frames N] [--skip-vlm]
  --skip-vlm：只抽帧不调 VLM（省 token，调试用）
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser(description="一键预处理：视频→攻略知识包")
    ap.add_argument("video_dir", nargs="?", default=None,
                    help="视频目录（默认 ingest/raw/videos）")
    ap.add_argument("--max-frames", type=int, default=300, help="每视频最大帧数")
    ap.add_argument("--skip-vlm", action="store_true", help="跳过 VLM 检测（只抽帧）")
    ap.add_argument("--pkg", default="black_tower_test", help="输出知识包名")
    args = ap.parse_args()

    video_dir = Path(args.video_dir) if args.video_dir \
        else ROOT / "ingest" / "raw" / "videos"
    videos = sorted(video_dir.glob("*.mp4"))
    if not videos:
        print(f"[pipeline] 无视频: {video_dir}")
        sys.exit(1)
    print(f"[pipeline] 视频 {len(videos)} 个")

    # 输出知识包目录（复制现有结构或创建）
    pkg_dir = ROOT / "knowledge" / "source" / args.pkg
    pkg_dir.mkdir(parents=True, exist_ok=True)

    from ingest.capture_frames import extract_frames, RESULTS_FILE, FRAME_DIR
    from ingest.capture_frames import ask_frame
    from ingest.vlm_client import QwenVLProvider

    all_results = []
    crops = {"chest": [], "door": [], "landmark": []}
    provider = QwenVLProvider() if not args.skip_vlm else None
    total_frames = 0
    for vi, video in enumerate(videos, 1):
        print(f"\n[pipeline] [{vi}/{len(videos)}] {video.name}")
        # 每视频独立帧子目录——多视频批处理帧名 f_%04d 不互覆盖
        # （extract_frames 默认全局 FRAME_DIR 会被下一视频清空）
        vd = FRAME_DIR / f"v{vi}"
        frames = extract_frames(video, max_frames=args.max_frames, frame_dir=vd)
        print(f"  抽帧 {len(frames)} 张")
        total_frames += len(frames)
        video_results = []
        for fi, f in enumerate(frames):
            if args.skip_vlm:
                rec = {"frame": f.name, "data": {"observation_only": True}}
                video_results.append(rec)
                continue
            data = ask_frame(provider, f, fi)
            found = [k for k, v in data.items()
                     if isinstance(v, dict) and v.get("found")]
            mark = f"  发现: {found}" if found else ""
            print(f"  f_{fi:04d} -> {data.get('room')}{mark}")
            video_results.append({"frame": f.name, "data": data})
        all_results += video_results
        # 每视频结果原子写（防中断丢进度）
        RESULTS_FILE.write_text(
            json.dumps(all_results, ensure_ascii=False, indent=2),
            encoding="utf-8")
        # 每视频立即裁剪（帧目录还活着；模板名带视频前缀防覆盖）
        if not args.skip_vlm:
            import ingest.crop_templates as ct
            for kind in ("chest", "door", "landmark"):
                crops[kind] += ct.crop(vd, video_results, f"v{vi}_{kind}", kind)
                print(f"[pipeline] 视频 {vi} 裁剪 {kind} {len(crops[kind])} 张")

    print(f"\n[pipeline] 共抽帧 {total_frames}，检测结果写入 results.json")

    if args.skip_vlm:
        print("[pipeline] --skip-vlm：裁剪/校验跳过（需先跑 VLM）")
        return

    # 裁剪汇总
    import ingest.crop_templates as ct
    for kind in ("chest", "door", "landmark"):
        print(f"[pipeline] 裁剪 {kind} 模板 {len(crops[kind])} 张")
    # 知识包校验
    from runtime.knowledge_loader import KnowledgePackage
    from ingest.compiler.validate_graph import validate
    pkg = KnowledgePackage(pkg_dir)
    errors, warnings = validate(pkg, verbose=True)
    print(f"\n[pipeline] 知识包校验: {len(errors)} error(s), {len(warnings)} warning(s)")
    print("[pipeline] 完成——如裁剪结果待人工确认，运行 review_templates.py")


if __name__ == "__main__":
    main()
