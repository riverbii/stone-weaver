#!/usr/bin/env python3
"""从 guihui_v3（癸酉本108回全文）提取后28回情节弧 → arcs 表 + docs/guihui_arc.md。

用法:
  .venv/bin/python scripts/build_arc.py --start 81 --end 108
  .venv/bin/python scripts/build_arc.py --only 81     # 重跑单回（会覆盖该回 beat）

进度: data/extract/progress_arc.txt（记录已完成回；重跑用 --force 或 --only）
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.engine.arc import (
    Arc,
    build_arc_from_chapters,
    load_arc,
    save_arc,
)
from stone_weaver.ingest.text import make_session
from stone_weaver.llm import LLMClient

ARC_NAME = "癸酉本后28回情节弧"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=81)
    ap.add_argument("--end", type=int, default=108)
    ap.add_argument("--only", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="忽略进度文件强制重跑")
    ap.add_argument("--db", default="data/db/stone.db")
    args = ap.parse_args()

    db = make_session(args.db)
    client = LLMClient()

    prog = ROOT / "data" / "extract" / "progress_arc.txt"
    prog.parent.mkdir(parents=True, exist_ok=True)
    done = (
        {int(x) for x in prog.read_text().splitlines() if x.strip()}
        if prog.exists()
        else set()
    )

    nums = [args.only] if args.only else list(range(args.start, args.end + 1))
    todo = [n for n in nums if n not in done or args.force]
    print(f"计划 {len(nums)} 回，已完成 {len(nums) - len(todo)}，本次跑 {len(todo)}", flush=True)

    t_start = time.time()
    for num in todo:
        # 单回提取 + 落库（覆盖式：arcs 表按"该回"重算，简单起见全弧重建）
        pass  # build_arc_from_chapters 一次性全量；单回场景直接调 extract_beat
    if args.only is None:
        arc = build_arc_from_chapters(
            db, client, [n for n in nums if n not in done or args.force]
        )
        aid = save_arc(db, arc)
        done |= set(nums)
        prog.write_text("\n".join(str(n) for n in sorted(done)) + "\n")
        print(f"\n✅ 情节弧已保存（arc id={aid}），{len(arc.beats)} 个 beat，总耗时 {(time.time()-t_start)/60:.1f} 分钟", flush=True)
        # 生成可读文档
        md = ["# 癸酉本后28回情节弧（引擎提取版）", "", f"> 来源：guihui_v3 逐回压缩 | {len(arc.beats)} beat | 生成于 {time.strftime('%Y-%m-%d %H:%M')}", ""]
        for i, b in enumerate(arc.beats, 1):
            ch = args.start + i - 1
            md.append(f"## 第{ch}回 · {b.scene or '—'}")
            md.append(f"- **目标**：{b.goal}")
            if b.characters:
                md.append(f"- **人物**：{'、'.join(b.characters)}")
            if b.constraints:
                md.append(f"- **约束**：{'；'.join(b.constraints)}")
            if b.expected_out:
                md.append(f"- **结果**：{b.expected_out}")
            md.append("")
        (ROOT / "docs" / "guihui_arc.md").write_text("\n".join(md), encoding="utf-8")
        print(f"可读版已写 docs/guihui_arc.md", flush=True)
    else:
        from stone_weaver.engine.arc import extract_beat
        from stone_weaver.models import Chapter

        ch = (
            db.query(Chapter)
            .filter(Chapter.version == "guihui_v3", Chapter.num == args.only)
            .first()
        )
        beat = extract_beat(client, ch)
        if beat is None:
            print(f"[{args.only}] ❌ 提取失败", flush=True)
            return 1
        # 载入现有弧替换该回 beat（按位置：num-81）
        from stone_weaver.models import Arc as ArcRow

        row = db.query(ArcRow).filter(ArcRow.name == ARC_NAME).first()
        beats = list(row.beats or []) if row else []
        idx = args.only - args.start
        if idx < len(beats):
            beats[idx] = beat.to_dict()
        else:
            beats.append(beat.to_dict())
        if row is None:
            row = ArcRow(name=ARC_NAME, version="guihui_v3")
            db.add(row)
        row.beats = beats
        row.source_chapter_range = f"{args.start}-{args.end}"
        db.commit()
        print(f"[{args.only}] ✅ 已更新该回 beat: {beat.goal[:40]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
