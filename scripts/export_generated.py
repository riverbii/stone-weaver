#!/usr/bin/env python3
"""导出引擎生成的 28 回正文为纯文本文件（项目资产，入库推送）。

用法:
  .venv/bin/python scripts/export_generated.py
产出: data/generated/81.txt ~ 108.txt（自家版本选定来源的正文）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.ingest.text import make_session
from stone_weaver.models import Chapter, GeneratedChapter


def main() -> int:
    db = make_session(str(ROOT / "data" / "db" / "stone.db"))

    # 自家版本选稿（原文 or 引擎）
    dec_path = ROOT / "data" / "self_decision.json"
    decision = json.loads(dec_path.read_text(encoding="utf-8"))

    out_dir = ROOT / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    n_engine = n_original = 0
    for num in range(81, 109):
        if decision.get(str(num)) == "original":
            ch = db.query(Chapter).filter(
                Chapter.version == "guihui_clean", Chapter.num == num
            ).first()
            n_original += 1
        else:
            ch = db.query(GeneratedChapter).filter(
                GeneratedChapter.num == num
            ).first()
            n_engine += 1
        if ch is None:
            print(f"⚠️ ch{num} 无内容", flush=True)
            continue
        (out_dir / f"{num}.txt").write_text(ch.content, encoding="utf-8")

    print(f"✅ 已导出 {n_engine} 回引擎版 + {n_original} 回原文 → data/generated/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
