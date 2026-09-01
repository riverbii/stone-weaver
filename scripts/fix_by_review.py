#!/usr/bin/env python3
"""审查驱动的修复：硬伤重写 + 格律修题曰 + 失败重审。

方案（用户确认）：
  1. 硬伤回（81/96/103）：审查→带反馈重写→再审查确认
  2. 格律回（83/88/89/95/101/107）：只重写题曰诗（正文文风 OK）
  3. ch94：重审（上次 LLM 未返回 JSON），失败则整体重写

用法:
  .venv/bin/python scripts/fix_by_review.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.engine.arc import load_arc
from stone_weaver.engine.generate import generate_tiyu
from stone_weaver.ingest.text import make_session
from stone_weaver.llm import LLMClient
from stone_weaver.models import GeneratedChapter
from stone_weaver.style.reviewer import StyleReviewer

ARC_ID = 2
ARC_START = 81

HARD = [81, 96, 103]      # 硬伤：重写正文+题曰
GEILV = [83, 88, 89, 95, 101, 107]  # 格律：只重写题曰
RETRY = [94]              # 重审


def split_tiyu_and_body(content: str) -> tuple[str, str]:
    """拆出 (题曰部分, 正文部分)。"""
    i = content.find("题曰")
    if i == -1:
        return "", content
    j = content.find("\n\n", i)
    if j == -1:
        return content, ""
    return content[:j], content[j:]


def main() -> int:
    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    client = LLMClient()
    reviewer = StyleReviewer(client, db)
    arc = load_arc(db, ARC_ID)

    results = {"hard": {}, "geilv": {}, "retry": {}}

    # 1. 硬伤回：审查→重写→再审查
    for num in HARD:
        g = db.query(GeneratedChapter).filter(GeneratedChapter.num == num).first()
        if g is None:
            print(f"ch{num}: 无记录", flush=True)
            continue
        idx = num - ARC_START
        beat = arc.beats[idx].to_dict()
        t0 = time.time()
        # 审查
        review = reviewer.review(g.content, beat=beat, title=g.title)
        if not review.has_errors():
            print(f"ch{num}: 审查已通过，无需重写", flush=True)
            results["hard"][num] = "already_ok"
            continue
        # 带反馈重写
        new_text = reviewer.rewrite_with_feedback(g.content, review)
        # 重写后重新生成题曰（带格律把关）
        tiyu = generate_tiyu(client, beat, g.title)
        if tiyu:
            _, body = split_tiyu_and_body(new_text)
            p = tiyu.strip()
            new_text = (f"{p}\n\n{body.lstrip()}") if p.startswith("题曰") else (f"题曰：\n{p}\n\n{body.lstrip()}")
        g.content = new_text
        db.commit()
        # 复查
        review2 = reviewer.review(g.content, beat=beat, title=g.title)
        status = "通过" if not review2.has_errors() else f"仍有问题:{review2.verdict}"
        results["hard"][num] = status
        print(f"ch{num}: 重写完成({time.time()-t0:.0f}s) 复查={status}", flush=True)

    # 2. 格律回：只重写题曰诗
    for num in GEILV:
        g = db.query(GeneratedChapter).filter(GeneratedChapter.num == num).first()
        idx = num - ARC_START
        beat = arc.beats[idx].to_dict()
        t0 = time.time()
        tiyu = generate_tiyu(client, beat, g.title)  # 带格律把关
        if tiyu:
            _, body = split_tiyu_and_body(g.content)
            p = tiyu.strip()
            new_head = (f"{p}\n\n{body.lstrip()}") if p.startswith("题曰") else (f"题曰：\n{p}\n\n{body.lstrip()}")
            g.content = new_head
            db.commit()
            results["geilv"][num] = "ok"
            print(f"ch{num}: 题曰重写完成({time.time()-t0:.0f}s) {p[:30]}", flush=True)
        else:
            print(f"ch{num}: 题曰生成失败", flush=True)

    # 3. ch94 重审
    for num in RETRY:
        g = db.query(GeneratedChapter).filter(GeneratedChapter.num == num).first()
        idx = num - ARC_START
        beat = arc.beats[idx].to_dict()
        t0 = time.time()
        review = reviewer.review(g.content, beat=beat, title=g.title)
        if not review.has_errors():
            results["retry"][num] = "通过"
            print(f"ch{num}: 重审通过", flush=True)
        else:
            new_text = reviewer.rewrite_with_feedback(g.content, review)
            g.content = new_text
            db.commit()
            results["retry"][num] = "重写"
            print(f"ch{num}: 重审有误→重写({time.time()-t0:.0f}s)", flush=True)

    out = ROOT / "data" / "fix_by_review_result.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n修复结果: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
