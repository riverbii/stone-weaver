#!/usr/bin/env python3
"""用 LLM 文风裁判重评癸酉本后28回（比手工规则准）。

用法:
  .venv/bin/python scripts/judge_guihui.py                # 全 28 回
  .venv/bin/python scripts/judge_guihui.py --only 103     # 单回
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.ingest.text import make_session
from stone_weaver.llm import LLMClient
from stone_weaver.models import Chapter
from stone_weaver.style.judge import judge_style

ANNOT_RE = re.compile(r"〔批(?:[:：][^〕]*)?〕.*?〔/批〕", re.S)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=None)
    ap.add_argument("--db", default="data/db/stone.db")
    args = ap.parse_args()

    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    client = LLMClient()

    report_path = ROOT / "data" / "guihui_judge_report.json"
    report = {}
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))

    nums = [args.only] if args.only else list(range(81, 109))
    for n in nums:
        if str(n) in report and not args.only:
            print(f"[{n}] 已评，跳过", flush=True)
            continue
        ch = (
            db.query(Chapter)
            .filter(Chapter.version == "guihui_v3", Chapter.num == n)
            .first()
        )
        if ch is None:
            continue
        text = ANNOT_RE.sub("", ch.content)
        t0 = time.time()
        r = judge_style(client, db, text)
        r["num"] = n
        r["title"] = ch.title
        report[str(n)] = r
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(
            f"[{n}] score={r['score']} ({r['verdict']}) 耗时{time.time()-t0:.0f}s "
            f"缺点: {'；'.join(r.get('weaknesses', [])[:1])[:60]}",
            flush=True,
        )

    # 汇总
    rows = [v for v in report.values() if isinstance(v, dict) and v.get("score") is not None]
    rows.sort(key=lambda r: -r["score"])
    print("\n" + "=" * 60)
    print("癸酉本后28回 LLM 文风裁判（0-10）")
    print("=" * 60)
    for r in rows:
        print(f"  ch{r['num']}: {r['score']:.1f} {r['verdict']}  {r['title'][:20]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
