#!/usr/bin/env python3
"""驱动叙事引擎逐回生成（阶段3：后28回重建）。

用法:
  # 先建好情节弧（arcs 表）：
  .venv/bin/python scripts/build_arc.py --start 81 --end 108
  # 然后逐回生成：
  .venv/bin/python scripts/generate_chapters.py --start 81 --end 108 --arc 1
  # 单回重试（只重生成该回）：
  .venv/bin/python scripts/generate_chapters.py --only 81 --arc 1 --force

流程（每回）：
  arc beat → simulate_one_beat（plan→generate→extract→validate→落库）
  规则校验失败自动带反馈重试；全部失败则跳过并记录。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.engine.arc import load_arc
from stone_weaver.engine.simulate import simulate_one_beat
from stone_weaver.ingest.text import make_session
from stone_weaver.llm import LLMClient
from stone_weaver.models import CharacterState, GeneratedChapter
from stone_weaver.style.anchors import extract_anchors
from stone_weaver.world.state import initial_state_from_events, state_at


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=81)
    ap.add_argument("--end", type=int, default=108)
    ap.add_argument("--only", type=int, default=None)
    ap.add_argument("--arc", type=int, required=True, help="arcs 表 id")
    ap.add_argument("--force", action="store_true", help="重生成已存在的回")
    ap.add_argument("--db", default="data/db/stone.db")
    ap.add_argument("--no-persist", action="store_true", help="只生成不落库（试运行）")
    args = ap.parse_args()

    db = make_session(args.db)
    client = LLMClient()

    arc = load_arc(db, args.arc)
    if not arc.beats:
        print("❌ 情节弧为空，先跑 scripts/build_arc.py")
        return 1
    print(f"情节弧「{arc.name}」{len(arc.beats)} beat", flush=True)

    # 风格锚点（公版前80回）
    anchors = extract_anchors(db, chapters=list(range(1, 81)), per_kind=2)
    print(f"风格锚点 {len(anchors)} 条", flush=True)

    # 80→81 世界状态（衔接点）：优先用 character_states 快照（LLM 核查版），
    # 无快照时退回规则推导
    from stone_weaver.world.state import state_at

    state = state_at(db, 80)
    n_snap = (
        db.query(CharacterState).filter(CharacterState.chapter == 80).count()
    )
    if n_snap == 0:
        print("无 ch80 快照，用规则推导（建议先跑 scripts/build_ch80_state.py）", flush=True)
        state = initial_state_from_events(db, chapter=80)
    print(f"ch80 世界状态（{n_snap} 条快照）:", flush=True)
    print(state.describe(limit=10), flush=True)

    nums = [args.only] if args.only else list(range(args.start, args.end + 1))
    t_start = time.time()
    for num in nums:
        if not args.force:
            exists = (
                db.query(GeneratedChapter)
                .filter(GeneratedChapter.num == num)
                .first()
            )
            if exists and exists.status != "draft":
                print(f"[{num}] 已生成（{exists.status}），跳过（--force 重做）", flush=True)
                continue
        idx = num - args.start
        if idx >= len(arc.beats):
            print(f"[{num}] ⚠️ 超出情节弧 beat 数，跳过", flush=True)
            continue
        beat = arc.beats[idx].to_dict()
        t0 = time.time()
        result = simulate_one_beat(
            db, client, beat, state, anchors,
            chapter_num=num,
            title=f"第{num}回（引擎重建）",
            max_retries=3,
            persist=not args.no_persist,
        )
        if result["ok"]:
            print(f"✅ [{num}] 生成成功（{result['retries']} 次重试）耗时 {time.time()-t0:.0f}s", flush=True)
            if not args.no_persist:
                # 更新状态到该回（simulate 内部已 apply）
                state.chapter = num
        else:
            print(f"❌ [{num}] 生成失败", flush=True)
            for v in result["violations"]:
                print(f"    [{v.severity}] {v.message}", flush=True)
    print(f"\n完成，总耗时 {(time.time()-t_start)/60:.1f} 分钟", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
