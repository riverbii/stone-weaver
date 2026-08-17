#!/usr/bin/env python3
"""批量关系提取：公版前80回 → relationships 表（分段 + 重试 + 断点续传）。

用法:
  .venv/bin/python scripts/extract_relationships.py --start 1 --end 80
  .venv/bin/python scripts/extract_relationships.py --only 3   # 重跑单回

依赖：characters 表已有人物（先跑 scripts/extract_characters.py）。
进度: data/extract/progress_relationships.txt
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.ingest.text import make_session
from stone_weaver.llm import LLMClient
from stone_weaver.models import Chapter
from stone_weaver.world.extract import (
    extract_relationships_from_text,
    save_relationships,
)

SEG_TARGET = 2500
MAX_RETRIES = 6
RETRY_BASE = 8


def segment(paragraphs: list[str], target: int = SEG_TARGET) -> list[str]:
    segs: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for p in paragraphs:
        if cur and cur_len + len(p) > target:
            segs.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(p)
        cur_len += len(p)
    if cur:
        segs.append("\n".join(cur))
    return segs


def chat_with_retry(client: LLMClient, text: str, chapter: int) -> list[dict]:
    last_err = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return extract_relationships_from_text(client, text, chapter)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:200]
            wait = RETRY_BASE * (2 ** (attempt - 1))
            print(f"    重试 {attempt}/{MAX_RETRIES}（等待 {wait}s）: {last_err}", flush=True)
            time.sleep(wait)
    print(f"    ❌ 段提取失败: {last_err}", flush=True)
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=80)
    ap.add_argument("--only", type=int, default=None)
    ap.add_argument("--version", default="gongban_rb", help="底本 version（统一版就绪后如 unified）")
    ap.add_argument("--db", default="data/db/stone.db")
    args = ap.parse_args()

    db = make_session(args.db)
    client = LLMClient()

    prog = ROOT / "data" / "extract" / f"progress_relationships_{args.version}.txt"
    prog.parent.mkdir(parents=True, exist_ok=True)
    done = (
        {int(x) for x in prog.read_text().splitlines() if x.strip()}
        if prog.exists()
        else set()
    )

    nums = [args.only] if args.only else list(range(args.start, args.end + 1))
    todo = [n for n in nums if n not in done]
    print(f"计划 {len(nums)} 回，已完成 {len(nums) - len(todo)}，本次跑 {len(todo)}", flush=True)

    t_start = time.time()
    for num in todo:
        ch = (
            db.query(Chapter)
            .filter(Chapter.version == args.version, Chapter.num == num)
            .first()
        )
        if ch is None:
            print(f"[{num}] ⚠️ 回目不存在", flush=True)
            continue
        segs = segment(ch.paragraphs)
        all_rels: list[dict] = []
        t0 = time.time()
        for i, seg in enumerate(segs, 1):
            rels = chat_with_retry(client, seg, num)
            all_rels.extend(rels)
            print(f"  [{num}] 段 {i}/{len(segs)}: {len(rels)} 条", flush=True)
        added = save_relationships(db, all_rels, num)
        done.add(num)
        prog.write_text("\n".join(str(n) for n in sorted(done)) + "\n")
        print(
            f"✅ [{num}] 回完成：新增 {added} 条关系（本回提取 {len(all_rels)}），耗时 {time.time()-t0:.0f}s",
            flush=True,
        )

    from stone_weaver.models import Relationship

    n = db.query(Relationship).count()
    print(f"\n全部完成：relationships 共 {n} 条，总耗时 {(time.time()-t_start)/60:.1f} 分钟", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
