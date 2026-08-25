#!/usr/bin/env python3
"""文风审查智能体 CLI：审查引擎回（文风/格律/意境/内容贴合四维）。

用法:
  .venv/bin/python scripts/review_chapters.py --only 82
  .venv/bin/python scripts/review_chapters.py            # 全部引擎回
  .venv/bin/python scripts/review_chapters.py --report   # 生成质量报告
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.engine.arc import load_arc
from stone_weaver.ingest.text import make_session
from stone_weaver.llm import LLMClient
from stone_weaver.models import GeneratedChapter
from stone_weaver.style.reviewer import StyleReviewer

ARC_ID = 2
ARC_START = 81


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=None)
    ap.add_argument("--report", action="store_true", help="写 JSON 报告")
    args = ap.parse_args()

    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    client = LLMClient()
    reviewer = StyleReviewer(client, db)
    arc = load_arc(db, ARC_ID)

    gs = db.query(GeneratedChapter).order_by(GeneratedChapter.num).all()
    if args.only:
        gs = [g for g in gs if g.num == args.only]
    if not gs:
        print("无引擎回")
        return 1

    results = {}
    for g in gs:
        idx = g.num - ARC_START
        beat = arc.beats[idx].to_dict() if 0 <= idx < len(arc.beats) else {}
        r = reviewer.review(g.content, beat=beat, title=g.title)
        scores = {d.dim: d.score for d in r.dims}
        ok = all(d.ok for d in r.dims)
        results[str(g.num)] = {
            "scores": scores,
            "verdict": r.verdict,
            "summary": r.summary,
            "issues": {d.dim: d.issues for d in r.dims if not d.ok},
        }
        print(
            f"ch{g.num}: {'✅' if ok else '❌'} "
            f"文风{scores.get('文风',0)} 格律{scores.get('格律',0)} "
            f"意境{scores.get('意境',0)} 贴合{scores.get('内容贴合',0)} | {r.summary[:30]}",
            flush=True,
        )

    if args.report:
        out = ROOT / "data" / "engine_review_report.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n报告: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
