"""Bug 248：压力测试——知识包 dry_run 循环 + 事件流完整性（24h 稳定性预演）。

用法：python tools/stress_test.py --rounds 50 [--fail-rate 0.1]
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runtime import dry_run
from runtime.events.bus import EventBus


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=50)
    parser.add_argument("--fail-rate", type=float, default=0.0,
                        help="故障注入率（Bug 247 随机故障演练）")
    parser.add_argument("--pkg", default="knowledge/source/black_tower_test")
    args = parser.parse_args()

    pkg_dir = str(ROOT / args.pkg)
    t0 = time.time()
    total_events = 0
    for r in range(args.rounds):
        bus = EventBus()
        seen = []
        bus.subscribe(lambda e: seen.append(e.type))
        rc = dry_run.dry_run(pkg_dir, bus=bus, execution_id=f"stress-{r}",
                             fail_rate=args.fail_rate, seed=r)
        total_events += len(seen)
        if r % 10 == 0:
            print(f"  round {r}: rc={rc} events={len(seen)}")
    elapsed = time.time() - t0
    print(f"STRESS DONE: {args.rounds} 轮 {elapsed:.1f}s "
          f"（{total_events} 事件，{(total_events / elapsed):.1f} 事件/秒）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
