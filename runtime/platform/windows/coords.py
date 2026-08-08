"""CoordinateSpace（Sprint D-8：DPI 统一层——业务代码禁止 x/scale 散落）。

March7th screenshot_scale_factor 已归一化截图；本模块把"逻辑↔物理"换算
收敛为单一实现，供校准/诊断工具使用（runtime 执行链不接触坐标）。
"""
from dataclasses import dataclass


@dataclass
class CoordinateSpace:
    logical_width: int = 1920
    logical_height: int = 1080
    physical_width: int = 1920
    physical_height: int = 1080
    scale: float = 1.0

    @classmethod
    def from_scale_factor(cls, scale, logical_w=1920, logical_h=1080):
        return cls(logical_width=logical_w, logical_height=logical_h,
                   physical_width=int(logical_w * scale),
                   physical_height=int(logical_h * scale),
                   scale=scale)


def logical_to_physical(x, y, space: CoordinateSpace):
    return int(x * space.scale), int(y * space.scale)


def physical_to_logical(x, y, space: CoordinateSpace):
    if space.scale <= 0:
        return int(x), int(y)
    return int(x / space.scale), int(y / space.scale)
