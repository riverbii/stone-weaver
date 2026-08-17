#!/usr/bin/env python3
"""批量人物提取：公版前80回 → characters 表（分段 + 指数退避重试 + 断点续传）。

用法:
  .venv/bin/python scripts/extract_characters.py --version gongban_rb --start 1 --end 80
  .venv/bin/python scripts/extract_characters.py --version gongban_rb --only 12   # 重跑单回

进度记录: data/extract/progress_characters_{version}.txt（每行一个已完成回号）
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
from stone_weaver.models import Chapter, Character
from stone_weaver.world.extract import extract_characters_from_text

SEG_TARGET = 2200  # 每段目标字符数（网关长文本不稳定，控制在 ~2200）
MAX_RETRIES = 6
RETRY_BASE = 8  # 首退 8s，指数退避 8/16/32/64/128/256


def segment(paragraphs: list[str], target: int = SEG_TARGET) -> list[str]:
    """把段落按目标字符数聚合成段（尽量不切句中）。"""
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


def chat_with_retry(client: LLMClient, text: str) -> list[dict]:
    """带指数退避重试的提取调用。"""
    last_err = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return extract_characters_from_text(client, text)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:200]
            wait = RETRY_BASE * (2 ** (attempt - 1))
            print(f"    重试 {attempt}/{MAX_RETRIES}（等待 {wait}s）: {last_err}", flush=True)
            time.sleep(wait)
    print(f"    ❌ 段提取失败（已重试 {MAX_RETRIES} 次）: {last_err}", flush=True)
    return []


def progress_path(version: str) -> Path:
    d = ROOT / "data" / "extract"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"progress_characters_{version}.txt"


def load_progress(version: str) -> set[int]:
    p = progress_path(version)
    if not p.exists():
        return set()
    return {int(line.strip()) for line in p.read_text().splitlines() if line.strip()}


def save_progress(version: str, done: set[int]) -> None:
    progress_path(version).write_text("\n".join(str(n) for n in sorted(done)) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="gongban_rb")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=80)
    ap.add_argument("--only", type=int, default=None, help="只处理单回（忽略 start/end）")
    ap.add_argument("--db", default="data/db/stone.db")
    args = ap.parse_args()

    db = make_session(args.db)
    client = LLMClient()
    done = load_progress(args.version)

    nums = [args.only] if args.only else list(range(args.start, args.end + 1))
    todo = [n for n in nums if n not in done]
    print(f"计划 {len(nums)} 回，已完成 {len(nums) - len(todo)} 回，本次跑 {len(todo)} 回", flush=True)

    t_start = time.time()
    for num in todo:
        ch = (
            db.query(Chapter)
            .filter(Chapter.version == args.version, Chapter.num == num)
            .first()
        )
        if ch is None:
            print(f"[{num}] ⚠️ 回目不存在，跳过", flush=True)
            continue
        segs = segment(ch.paragraphs)
        chapter_chars: list[dict] = []
        t0 = time.time()
        for i, seg in enumerate(segs, 1):
            chars = chat_with_retry(client, seg)
            chapter_chars.extend(chars)
            print(
                f"  [{num}] 段 {i}/{len(segs)}: {len(chars)} 人（累计 {len(chapter_chars)}）",
                flush=True,
            )
        # 合并入库 + first_chapter（取最小出现回）
        from stone_weaver.world.extract import save_characters

        added = save_characters(db, chapter_chars, source_version=args.version)
        for c in chapter_chars:
            name = c["name"].strip()
            if not name:
                continue
            rec = db.query(Character).filter(Character.name == name).first()
            if rec is not None and (rec.first_chapter is None or num < rec.first_chapter):
                rec.first_chapter = num
        db.commit()
        done.add(num)
        save_progress(args.version, done)
        print(
            f"✅ [{num}] 回完成：新增 {added} 人，本回提取 {len(chapter_chars)} 条，耗时 {time.time()-t0:.0f}s",
            flush=True,
        )

    n = db.query(Character).count()
    print(f"\n全部完成：characters 表共 {n} 人，总耗时 {(time.time()-t_start)/60:.1f} 分钟", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
