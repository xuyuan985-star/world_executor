"""Bug 570/571：统一随机源——可复现测试约定。

所有随机行为（naturalness/dry_run 故障注入/噪声模拟）必须用
random.Random(seed)，禁止裸 random 模块。测试固定 seed=42。
"""
import random

TEST_SEED = 42  # 测试固定种子（Bug 571：同测试同结果）


def rng(seed=None):
    """全局统一随机源：显式 seed 优先，否则固定 TEST_SEED（测试可复现）。"""
    return random.Random(TEST_SEED if seed is None else seed)
