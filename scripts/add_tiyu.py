#!/usr/bin/env python3
"""给已生成的引擎回补"题曰"开篇诗（不重生成正文，只前置诗）。

用法:
  .venv/bin/python scripts/add_tiyu.py                  # 全部引擎回
  .venv/bin/python scripts/add_tiyu.py --only 82        # 单回
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.engine.arc import load_arc
from stone_weaver.engine.generate import generate_tiyu
from stone_weaver.ingest.text import make_session
from stone_weaver.llm import LLMClient
from stone_weaver.models import GeneratedChapter

# arc 2：81-108，beats[idx] 对应 ch{81+idx}
ARC_ID = 2
ARC_START = 81


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=None)
    ap.add_argument("--db", default="data/db/stone.db")
    args = ap.parse_args()

    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    client = LLMClient()
    arc = load_arc(db, ARC_ID)

    gs = db.query(GeneratedChapter).order_by(GeneratedChapter.num).all()
    if args.only:
        gs = [g for g in gs if g.num == args.only]
    if not gs:
        print("无引擎回可处理")
        return 1

    for g in gs:
        idx = g.num - ARC_START
        beat = arc.beats[idx].to_dict() if 0 <= idx < len(arc.beats) else {}
        # 检查是否已有题曰
        if g.content.strip().startswith("题曰"):
            print(f"ch{g.num}: 已有题曰，跳过", flush=True)
            continue
        tiyu = generate_tiyu(client, beat, g.title)
        if not tiyu:
            print(f"ch{g.num}: ❌ 题曰生成失败", flush=True)
            continue
        if tiyu.strip().startswith("题曰"):
            g.content = f"{tiyu}\n\n{g.content}"
        else:
            g.content = f"题曰：\n{tiyu}\n\n{g.content}"
        db.commit()
        print(f"ch{g.num}: ✅ 已补题曰「{tiyu.strip()[:30]}…」", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
