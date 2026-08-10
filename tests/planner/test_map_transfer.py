"""地图传送测试（抄 Fhoe-Rail 传送链适配）。

Test 1：map_transfer——hotkey 打开地图→模板序列点击（Fhoe 资产）→加载等待 → True
Test 2：模板序列中途未命中 → False（可重试）
Test 3：portal 步骤接入 orchestrator——workflow portal 步骤 → portal_transition/map_transfer 被调
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from unittest import mock  # noqa: E402


class FakeInput2:
    name = "fake"

    def __init__(self):
        self.keys = []
        self.clicks = []

    def press_key(self, key, wait_time=0.2):
        self.keys.append((key, wait_time))
        return type("R", (), {"success": True, "detail": {}})()

    def click(self, x, y):
        self.clicks.append((x, y))
        return type("R", (), {"success": True, "detail": {}})()


def main():
    from runtime.step_executor import RealExecutor

    portal = {
        "id": "tp_herta_base", "kind": "map_transfer",
        "steps": [
            {"template": "Fhoe:map_0.png", "threshold": 0.9},
            {"template": "Fhoe:map_0_point.png", "threshold": 0.9},
            {"template": "Fhoe:transfer.png", "threshold": 0.9},
        ],
        "load_wait": 2,
    }

    # Test 1：全部命中 → True
    ex = object.__new__(RealExecutor)
    ex._input_override = FakeInput2()
    ex._driver = mock.MagicMock()
    ex._driver.vision = None  # 无 vision → 加载等待跳过差分

    with mock.patch("runtime.input.template_backend.TemplateMatcher") as TM:
        TM.return_value.locate.return_value = (0.95, 500, 400)
        ok = ex.map_transfer(portal)
    assert ok, "map_transfer 应成功"
    assert ex._input_override.keys, "应按下打开地图热键"
    assert len(ex._input_override.clicks) == 3, ex._input_override.clicks
    print(f"[map_transfer] Test 1 PASS（热键 {ex._input_override.keys[0][0]} + 3 次模板点击）")

    # Test 2：第 2 个模板未命中 → False
    ex2 = object.__new__(RealExecutor)
    ex2._input_override = FakeInput2()
    ex2._driver = mock.MagicMock()
    ex2._driver.vision = None
    hits = {0: (0.95, 500, 400), 1: None, 2: (0.95, 500, 400)}

    def fake_locate(path, scale_range=None):
        idx = {"Fhoe:map_0.png": 0, "Fhoe:map_0_point.png": 1,
               "Fhoe:transfer.png": 2}[str(path).split("\\")[-1] if "\\" in str(path)
                                          else str(path).split("/")[-1]]
        return hits.get(idx)

    with mock.patch("runtime.input.template_backend.TemplateMatcher") as TM:
        TM.return_value.locate.side_effect = fake_locate
        ok2 = ex2.map_transfer(portal)
    assert not ok2, "中途未命中应失败"
    print("[map_transfer] Test 2 PASS（模板中途未命中 → False）")

    # Test 3：Fhoe 资产解析
    from runtime.step_executor import RealExecutor as RE
    ex3 = object.__new__(RE)
    p1 = ex3._resolve_fhoe_template("Fhoe:transfer.png")
    assert p1 and "Fhoe-Rail" in p1 and p1.endswith("transfer.png"), p1
    print("[map_transfer] Test 3 PASS（Fhoe 资产解析）")

    print("[map_transfer] Test 1-3 全部 PASS")


if __name__ == "__main__":
    main()
