#!/usr/bin/env python3
"""批量地点提取：公版前80回 → locations 表（分段 + 重试 + 断点续传）。

用法:
  .venv/bin/python scripts/extract_locations.py --start 1 --end 80
  .venv/bin/python scripts/extract_locations.py --only 3   # 重跑单回

进度: data/extract/progress_locations.txt
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
from stone_weaver.models import Chapter, Location

SEG_TARGET = 3000
MAX_RETRIES = 6
RETRY_BASE = 8

LOCATION_PROMPT = """你是红楼梦研究助手。下面是第{chapter}回原文片段。请提取其中出现的**地点**。

要求：只输出 JSON 数组，不要其他文字。每个元素格式：
{{"name": "地点名", "kind": "府邸/园景/寺庙/街市/房间/仙幻/其他", "description": "本段体现的地点特征简述"}}

只提取本故事中的实际地点（如 荣国府/大观园/潇湘馆/宁荣街/葫芦庙/太虚幻境），
排除泛泛而谈的方位词（如"家中/屋里/街上"这种无专名的）。如无，输出 []。

原文：
{text}
"""


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


def parse_json_list(raw: str) -> list[dict]:
    import json

    s = raw.strip()
    a, b = s.find("["), s.rfind("]")
    if a == -1 or b <= a:
        return []
    try:
        data = json.loads(s[a : b + 1])
    except Exception:
        return []
    return [d for d in data if isinstance(d, dict) and d.get("name")] if isinstance(data, list) else []


def chat_with_retry(client: LLMClient, text: str, chapter: int) -> list[dict]:
    last_err = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            content = (
                LOCATION_PROMPT.replace("{{", "{")
                .replace("}}", "}")
                .replace("{text}", text[:6000])
                .replace("{chapter}", str(chapter))
            )
            raw = client.chat(
                [{"role": "system", "content": content}], temperature=0.1
            )
            return parse_json_list(raw)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:200]
            wait = RETRY_BASE * (2 ** (attempt - 1))
            print(f"    重试 {attempt}/{MAX_RETRIES}（等待 {wait}s）: {last_err}", flush=True)
            time.sleep(wait)
    print(f"    ❌ 段提取失败: {last_err}", flush=True)
    return []


def save_locations(db, locs: list[dict]) -> int:
    added = 0
    for loc in locs:
        name = (loc.get("name") or "").strip()
        if not name or len(name) <= 1:
            continue
        exists = db.query(Location).filter(Location.name == name).first()
        if exists:
            if loc.get("kind") and not exists.kind:
                exists.kind = loc["kind"]
            if loc.get("description") and not exists.description:
                exists.description = loc["description"]
            continue
        db.add(
            Location(
                name=name,
                kind=loc.get("kind") or None,
                description=loc.get("description") or None,
            )
        )
        added += 1
    db.commit()
    return added


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

    prog = ROOT / "data" / "extract" / f"progress_locations_{args.version}.txt"
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
        all_locs: list[dict] = []
        t0 = time.time()
        for i, seg in enumerate(segs, 1):
            locs = chat_with_retry(client, seg, num)
            all_locs.extend(locs)
            print(f"  [{num}] 段 {i}/{len(segs)}: {len(locs)} 个", flush=True)
        added = save_locations(db, all_locs)
        done.add(num)
        prog.write_text("\n".join(str(n) for n in sorted(done)) + "\n")
        print(
            f"✅ [{num}] 回完成：新增 {added} 个地点（本回提取 {len(all_locs)}），耗时 {time.time()-t0:.0f}s",
            flush=True,
        )

    n = db.query(Location).count()
    print(f"\n全部完成：locations 共 {n} 个，总耗时 {(time.time()-t_start)/60:.1f} 分钟", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
