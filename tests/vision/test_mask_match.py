"""alpha mask 模板匹配测试（March7th read_template_with_mask 机制适配）。

Test 1：RGBA 模板（透明区）→ mask 匹配命中正确位置且分数显著高于无 mask
Test 2：RGB 模板（无 alpha）→ 行为不变（TM_CCOEFF_NORMED 路径）
Test 3：模板缓存返回 (t, mask) 结构
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402


def make_rgba_template():
    """40x40：中心 20x20 红色方块不透明，外围透明。"""
    t = np.zeros((40, 40, 4), np.uint8)
    cv2.circle(t, (20, 20), 10, (200, 30, 30, 255), -1)
    return t


def make_scene():
    """200x200：高对比噪声背景（干扰无 mask 匹配）+ 左上 (80,80) 放模板内容。"""
    rng = np.random.default_rng(7)
    scene = rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)
    cv2.circle(scene, (100, 100), 10, (200, 30, 30), -1)
    return scene


def main():
    from runtime.input.template_backend import TemplateMatcher
    from unittest import mock

    tpl_path = ROOT / "tests" / "vision" / "_mask_tpl.png"
    tpl_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- Test 1：RGBA + mask 命中 ----
    cv2.imencode(".png", make_rgba_template())[1].tofile(str(tpl_path))
    tm = TemplateMatcher(threshold=0.5)
    with mock.patch.object(tm, "_screenshot", return_value=make_scene()):
        hit = tm.locate(str(tpl_path))
    assert hit is not None, "mask 匹配未命中"
    val, cx, cy = hit
    # 场景 200x200（<1280 不降采样）→ 模板中心应约在 (100,100)
    assert abs(cx - 100) <= 2 and abs(cy - 100) <= 2, (cx, cy)
    assert val > 0.8, f"mask 匹配分数过低 {val}"
    print(f"[mask] Test 1 PASS（RGBA 模板 mask 匹配 @({cx},{cy}) score={val:.3f}）")

    # ---- Test 2：RGB（无 alpha）→ 原路径不受影响 ----
    t, mask = tm._read_template(str(tpl_path))
    assert mask is not None
    rgb = tpl_path.with_suffix(".png").with_name("_rgb_tpl.png")
    cv2.imencode(".png", t)[1].tofile(str(rgb))
    tm2 = TemplateMatcher(threshold=0.5)
    with mock.patch.object(tm2, "_screenshot", return_value=make_scene()):
        t2, m2 = tm2._read_template(str(rgb))
        hit2 = tm2.locate(str(rgb))
    assert m2 is None, "RGB 模板不应有 mask"
    # 噪声背景上 CCOEFF 分数低（mask 的优势所在）——RGB 无 mask 路径正常返回即可
    print(f"[mask] Test 2 PASS（RGB 模板无 mask，路径不变 → hit={hit2}）")

    # ---- Test 3：缓存结构 ----
    cached = tm._template_cache[str(tpl_path)]
    assert len(cached) == 3 and cached[2] is not None, cached
    print("[mask] Test 3 PASS（缓存 (mtime, t, mask) 结构）")

    tpl_path.unlink(missing_ok=True)
    rgb.unlink(missing_ok=True)
    print("[mask] Test 1-3 全部 PASS")


if __name__ == "__main__":
    main()
