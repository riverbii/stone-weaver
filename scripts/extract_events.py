#!/usr/bin/env python3
"""批量事件提取：公版前80回 → events 表（情节有向图的节点）。

用法:
  .venv/bin/python scripts/extract_events.py --start 1 --end 80
  .venv/bin/python scripts/extract_events.py --only 3   # 重跑单回

依赖：characters 表已有人物（先跑 scripts/extract_characters.py）。
进度: data/extract/progress_events.txt
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
from stone_weaver.models import Chapter, Character, Event

SEG_TARGET = 3000
MAX_RETRIES = 6
RETRY_BASE = 8

EVENT_PROMPT = """你是红楼梦研究助手。下面是第{chapter}回原文片段。请提取其中发生的**情节事件**（按时间顺序）。

要求：只输出 JSON 数组，不要其他文字。每个元素格式：
{{"seq": 1, "summary": "事件简述（含人物动作）", "participants": ["人物标准姓名"], "location": "地点名，未知留空"}}

规则：
- seq 从 1 开始按发生顺序递增
- summary 用一句话概括"谁做了什么"
- participants 只放本故事人物（故事外典故人物不放）
- 事件粒度：一个连续场景动作为一个事件（如"贾雨村宴请冷子兴论贾府"），不要拆太碎
如无，输出 []。

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
    return [d for d in data if isinstance(d, dict) and d.get("summary")] if isinstance(data, list) else []


def chat_with_retry(client: LLMClient, text: str, chapter: int) -> list[dict]:
    last_err = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            content = EVENT_PROMPT.replace("{text}", text[:6000]).replace(
                "{chapter}", str(chapter)
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

    prog = ROOT / "data" / "extract" / f"progress_events_{args.version}.txt"
    prog.parent.mkdir(parents=True, exist_ok=True)
    done = (
        {int(x) for x in prog.read_text().splitlines() if x.strip()}
        if prog.exists()
        else set()
    )

    nums = [args.only] if args.only else list(range(args.start, args.end + 1))
    todo = [n for n in nums if n not in done]
    print(f"计划 {len(nums)} 回，已完成 {len(nums) - len(todo)}，本次跑 {len(todo)}", flush=True)

    # 人物名 → id 映射（participants 落库用）
    char_id = {c.name: c.id for c in db.query(Character).all()}

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
        all_events: list[dict] = []
        t0 = time.time()
        for i, seg in enumerate(segs, 1):
            evs = chat_with_retry(client, seg, num)
            all_events.extend(evs)
            print(f"  [{num}] 段 {i}/{len(segs)}: {len(evs)} 个", flush=True)

        # 段内 seq 重整为全局顺序
        for i, e in enumerate(all_events):
            e["seq"] = i + 1

        # 入库（幂等：先删该回旧事件）
        db.query(Event).filter(
            Event.chapter_id == ch.id
        ).delete()
        for e in all_events:
            pids = [
                char_id[p]
                for p in (e.get("participants") or [])
                if p in char_id
            ]
            db.add(
                Event(
                    chapter_id=ch.id,
                    seq=e.get("seq", 1),
                    summary=e.get("summary", ""),
                    participants=pids,
                    location=e.get("location") or None,
                )
            )
        db.commit()
        done.add(num)
        prog.write_text("\n".join(str(n) for n in sorted(done)) + "\n")
        print(
            f"✅ [{num}] 回完成：{len(all_events)} 个事件，耗时 {time.time()-t0:.0f}s",
            flush=True,
        )

    n = db.query(Event).count()
    print(f"\n全部完成：events 共 {n} 条，总耗时 {(time.time()-t_start)/60:.1f} 分钟", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
