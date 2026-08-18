#!/usr/bin/env python3
"""慢速抓取维基文库程甲本前80回（断点续传，抗限流）。

用法: .venv/bin/python scripts/fetch_chengjia_slow.py [--start N]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from stone_weaver.models import Chapter
from stone_weaver.ingest.text import make_session, clean_text

DB = ROOT / "data" / "db" / "stone.db"
API = "https://zh.wikisource.org/w/api.php"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

CN_DIGITS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
CN = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "〇": 0,
    "零": 0,
}


def cn_num(n: int) -> str:
    digits = {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
    }
    if n <= 10:
        return "十" if n == 10 else digits[n]
    tens, ones = divmod(n, 10)
    prefix = digits[tens] if tens > 1 else ""
    if ones == 0:
        return f"{prefix}十"
    return f"{prefix}十{digits[ones]}"


def api_get(params: dict, max_retries: int = 20) -> dict:
    params["format"] = "json"
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                wait = 30 * (attempt + 1)
                print(f"  限流({e.code})，等 {wait}s (第{attempt + 1}次)")
                time.sleep(wait)
                continue
            raise
        except Exception as ex:
            print(f"  异常 {ex}，等 30s")
            time.sleep(30)
    raise RuntimeError("限流重试耗尽")


def fetch_chapter(num: int) -> tuple[str, str]:
    """抓取程甲本一回，返回 (title, content)。"""
    page = f"紅樓夢（程甲本）/{cn_num(num)}"
    d = api_get({"action": "parse", "page": page, "prop": "text"})
    h = d["parse"]["text"]["*"]
    # 清理 HTML
    h = re.sub(r"\.mw-parser-output[^{]*\{[^}]*\}", "", h)
    text = html.unescape(re.sub(r"<[^>]+>", "", h))
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    noise = {
        "目錄",
        "紅樓夢（程甲本）",
        "全書始",
        "下一回▶",
        "上一回▶",
        "◀上一回",
        "下一回▶",
        "下一回",
        "上一回",
        "回目錄",
        "返回",
    }
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s in noise or s.startswith("◀") or s.endswith("▶"):
            continue
        lines.append(s)
    # 提取标题（"第X回 xxx"），并从正文剔除该行
    title = ""
    clean_lines = []
    for line in lines:
        m = re.match(r"^\s*第[一二三四五六七八九十百零〇\d]+回\s*(.*)$", line)
        if m:
            if not title:
                title = m.group(1).strip()
            continue  # 回目行不进入正文
        clean_lines.append(line)
    body = "\n".join(clean_lines)
    return title, clean_text(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=80)
    args = ap.parse_args()

    session: Session = make_session(str(DB))
    try:
        for num in range(args.start, args.end + 1):
            # 断点：已有则跳过
            existing = (
                session.query(Chapter)
                .filter(Chapter.version == "chengjia", Chapter.num == num)
                .one_or_none()
            )
            if existing and existing.content:
                print(f"  ch{num} 已有，跳过")
                continue
            try:
                title, body = fetch_chapter(num)
                if not body:
                    print(f"  !! ch{num} 正文为空")
                    continue
                if existing is None:
                    existing = Chapter(
                        num=num, version="chengjia", title=title, content=body
                    )
                    session.add(existing)
                else:
                    existing.title = title
                    existing.content = body
                session.commit()
                print(f"  ch{num} ok ({len(body)}字) {title[:20]}")
            except RuntimeError as e:
                print(f"  !! ch{num} 失败: {e}")
                break
            time.sleep(4)  # 每回间隔，降低频率
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
