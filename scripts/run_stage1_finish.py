#!/usr/bin/env python3
"""阶段1 收尾串行执行器：人物提取完成后，按序跑完剩余提取任务。

设计（网关限流约束）：
  - 严格串行，每个任务完成后休息 COOLDOWN 秒再跑下一个
  - 每个任务可独立跳过（已完成的看进度文件）
  - 用法：.venv/bin/python scripts/run_stage1_finish.py [--skip characters]

顺序：
  0. (可选) merge_characters 归并
  1. relationships 提取
  2. locations 提取
  3. events 提取
  4. build_arc 后28回情节弧
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "bin" / "python")

COOLDOWN = 120  # 任务间冷却秒数


def run(cmd: list[str]) -> int:
    print(f"\n{'='*60}\n>>> {' '.join(cmd)}\n{'='*60}", flush=True)
    return subprocess.call([PY, *cmd], cwd=str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", default="", help="逗号分隔要跳过的阶段名: characters,relationships,locations,events,arc,merge")
    ap.add_argument("--version", default="gongban_rb", help="底本 version")
    ap.add_argument("--cooldown", type=int, default=COOLDOWN)
    args = ap.parse_args()
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    steps = []

    if "merge" not in skip:
        steps.append(("merge", ["scripts/merge_characters.py", "--apply"]))
    if "relationships" not in skip:
        steps.append(("relationships", ["scripts/extract_relationships.py", "--start", "1", "--end", "80", "--version", args.version]))
    if "locations" not in skip:
        steps.append(("locations", ["scripts/extract_locations.py", "--start", "1", "--end", "80", "--version", args.version]))
    if "events" not in skip:
        steps.append(("events", ["scripts/extract_events.py", "--start", "1", "--end", "80", "--version", args.version]))
    if "arc" not in skip:
        steps.append(("arc", ["scripts/build_arc.py", "--start", "81", "--end", "108"]))

    t_start = time.time()
    for name, cmd in steps:
        rc = run(cmd)
        if rc != 0:
            print(f"⚠️ 阶段 [{name}] 返回码 {rc}，继续下一个（可在之后单独重跑）", flush=True)
        if name != steps[-1][0]:
            print(f"冷却 {args.cooldown}s 后继续（网关限流保护）…", flush=True)
            time.sleep(args.cooldown)
    print(f"\n阶段1 收尾完成，总耗时 {(time.time()-t_start)/60:.1f} 分钟", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
