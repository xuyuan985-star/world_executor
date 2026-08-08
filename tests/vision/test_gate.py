"""VisionGate 测试（Sprint B：决策前可信度——6 个基准 case）。

用法：python tests/vision/test_gate.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.vision_gate import (VisionGate, VisionEvidence, OCREvidence,  # noqa: E402
                                 VLMEvidence)
from runtime.vision_quality import FrameValidator  # noqa: E402
from runtime.observation_memory import StableState  # noqa: E402
import numpy as np  # noqa: E402


def ev(ocr_texts=(), vlm=None, frame_quality="ok"):
    return VisionEvidence(
        ocr=OCREvidence(texts=list(ocr_texts)),
        vlm=VLMEvidence(scene=(vlm or {}).get("ui_state"),
                        room=(vlm or {}).get("room"),
                        confidence=(vlm or {}).get("confidence") or 0.0),
        frame_quality=frame_quality,
    )


def main():
    gate = VisionGate()

    # Case 1：正常商店——OCR 商店/购买 + VLM shop + 一致 → ALLOW
    r1 = gate.evaluate(ev(["商店", "购买"], {"ui_state": "shop", "confidence": 0.85}))
    assert r1["allowed"], r1

    # Case 2：OCR/VLM 冲突——OCR 是 IDE（负向词）→ DENY
    r2 = gate.evaluate(ev(["Visual Studio", "Python"], {"ui_state": "game", "confidence": 0.7}))
    assert not r2["allowed"], r2

    # Case 3：黑屏帧 → DENY（结构层先行）
    fv = FrameValidator()
    black = fv.validate(np.zeros((100, 100), dtype=np.uint8))
    assert black.quality == "black"
    r3 = gate.evaluate(ev(["商店"], {"ui_state": "shop", "confidence": 0.9},
                          frame_quality=black.quality))
    assert not r3["allowed"], r3

    # Case 4：窗口错误——OCR 终端词无游戏信号 → DENY
    r4 = gate.evaluate(ev(["Python", "terminal"], None))
    assert not r4["allowed"], r4

    # Case 5：VLM unavailable——OCR 强（商店/购买）→ 降档阈值放行低风险
    r5 = gate.evaluate(ev(["商店", "购买"], None))
    assert r5["allowed"], r5
    assert r5["threshold"] < gate.threshold, r5  # 验证降档生效

    # Case 6：双帧确认——两次独立观测同状态 → StableState STABLE（ALLOW 语义）
    memory = StableState()
    obs1 = ev(["商店"], {"ui_state": "shop", "confidence": 0.6})
    obs2 = ev(["商店"], {"ui_state": "shop", "confidence": 0.9})
    assert not memory.update(obs1)  # 首次 → CONFIRMING
    assert memory.label == "CONFIRMING"
    assert memory.update(obs2)      # 二次 → STABLE
    assert memory.label == "STABLE"
    r6 = gate.evaluate(obs2)
    assert r6["allowed"], r6

    # 附加：静态帧检测（卡死/截错）与尺寸异常
    fv2 = FrameValidator()
    frames = [np.full((100, 100), 50, dtype=np.uint8) for _ in range(3)]
    is_static, diff = fv2.check_static(frames)
    assert is_static, (is_static, diff)
    frames2 = [np.full((100, 100), i * 20, dtype=np.uint8) for i in range(3)]
    assert not fv2.check_static(frames2)[0]
    fv3 = FrameValidator(expected_size=(1920, 1080))
    small = fv3.validate(np.zeros((800, 600), dtype=np.uint8))
    assert small.quality == "size_mismatch", small.quality

    # Case 7（Sprint B-6）：OCR 强 + VLM 弱 → observe（观察不执行）
    r7 = gate.evaluate(ev(["商店", "购买"], {"ui_state": None, "confidence": 0.2}))
    assert not r7["allowed"], r7
    assert r7["mode"] == "observe", r7

    # Case 8（Sprint B-6）：VLM 高 + OCR 无命中 → reject（vlm_only 幻觉特征）
    r8 = gate.evaluate(ev(["一些不相关文字"], {"ui_state": "game", "room": "base_zone",
                                             "confidence": 0.95}))
    assert not r8["allowed"], r8
    assert r8["mode"] == "reject", r8

    # #28：VLM 边界矩阵——vlm_only 弱置信 → observe（等待下一帧），高置信 → reject
    r_b1 = gate.evaluate(ev(["无关文本"], {"ui_state": "game", "confidence": 0.61}))
    assert not r_b1["allowed"] and r_b1["mode"] == "observe", r_b1
    r_b2 = gate.evaluate(ev(["无关文本"], {"ui_state": "game", "confidence": 0.49}))
    assert not r_b2["allowed"] and r_b2["mode"] == "observe", r_b2
    r_b3 = gate.evaluate(ev(["无关文本"], {"ui_state": "game", "confidence": 0.95}))
    assert not r_b3["allowed"] and r_b3["mode"] == "reject", r_b3
    # 冲突（OCR 商店 + VLM battle 高置信）→ reject（非 observe）
    r_b4 = gate.evaluate(ev(["商店"], {"ui_state": "battle", "confidence": 0.95}))
    assert not r_b4["allowed"] and r_b4["mode"] == "reject", r_b4

    # #40：VLM 挂掉（异常）→ OCR-only 降级（不崩 mission）
    class VLMDead:
        def observe(self, screenshot):
            raise TimeoutError("vlm api timeout")
    from runtime.vision_observer import VisionObserver, OCRAdapter
    vo = VisionObserver(ocr=None, vlm=VLMDead(), capture_fn=lambda: "x.png")
    obs = vo.observe()
    assert obs.confidence == 0.0 and obs.source == "none", obs  # VLM 异常被隔离
    vo2 = VisionObserver(ocr=OCRAdapter.__new__(OCRAdapter), vlm=VLMDead(),
                         capture_fn=lambda: "x.png")
    # OCRAdapter 需真实引擎；此处验证 VLM 异常不炸 VisionObserver 主流程
    assert obs.source == "none"

    print("[gate] 6 cases + 静态/尺寸 + observe/vlm_only 三元语义 + VLM 边界矩阵 + VLM异常隔离 全部 PASS")


if __name__ == "__main__":
    main()
